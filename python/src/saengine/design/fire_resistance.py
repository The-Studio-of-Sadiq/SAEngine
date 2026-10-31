"""Fire resistance of the concrete members by least sizes and covers.

The ratings (hours) are the project's (Project Settings → Analysis model → Fire resistance): the
fire resistance BNBC 2020 Part 4 requires for the building's occupancy and construction type.
BNBC 2020 Part 6 gives no table of the sizes that achieve a rating, so the pack's
``fireResistance`` table holds those of ACI 216.1-14, the standard ACI 318 refers to (siliceous
aggregate, the least favourable; slabs and beams unrestrained):

- slabs: thickness (Table 4.2) and the clear cover to the bottom bars (Table 4.3.1.1);
- structural walls: thickness (Table 4.2);
- beams: the clear cover to the main bars (Table 4.3.1.2, beams at least 254 mm wide; a
  narrower beam is reported as outside the table);
- columns: the least dimension (Table 4.5.1a) and the clear cover to the main bars, 25 mm per
  hour up to 50 mm (Sec 4.5.3).

Each is a detailing check added to the member's checks. Covers to the main bars are the clear
cover to the ties or stirrups plus their diameter.
"""

from __future__ import annotations

from typing import Any

from saengine.codes import context as code_context

__all__ = ["CLAUSE", "add_fire_checks", "required"]

CLAUSE = "ACI 216.1-14"
RATINGS = "BNBC 2020 Part 4"


def _table() -> Any:
    return code_context.pack_table("fireResistance")


def required(name: str, hours: float) -> float | None:
    """The table's ``name`` row at ``hours`` (the next rating up), or None above the table."""
    table = _table()
    for rating, value in zip(table.ratings, getattr(table, name), strict=True):
        if hours <= rating + 1e-9:
            return float(value)
    return None


def _check(name: str, need: float | None, given: float, hours: float, clause: str) -> dict:
    from saengine.design.check import _check as row

    if need is None:
        return row(
            f"Fire resistance: {name}",
            1.0,
            0.0,
            "mm",
            None,
            f"{hours:g} h is beyond the table ({CLAUSE}); check by another method",
        )
    return row(
        f"Fire resistance: {name}",
        need,
        given,
        "mm",
        None,
        f"{hours:g} h ({RATINGS}): at least {need:g} mm ({CLAUSE} {clause})",
    )


def _transverse_dia(object_type: Any) -> float:
    transverse = getattr(getattr(object_type, "reinforcement", None), "transverse", None)
    return float(transverse.dia) if transverse is not None else 0.0


def member_checks(kind: str, object_type: Any, hours: float) -> list[dict[str, Any]]:
    """The fire checks of one member of ``kind`` ("beam", "column", "slab", "wall")."""
    if hours <= 0 or object_type is None:
        return []
    table = _table()
    rows: list[dict[str, Any]] = []
    reinforcement = getattr(object_type, "reinforcement", None)
    cover = float(getattr(reinforcement, "cover", 0.0) or 0.0)
    if kind == "slab":
        rows.append(
            _check(
                "thickness",
                required("slabThickness", hours),
                float(object_type.thickness),
                hours,
                "Table 4.2",
            )
        )
        if reinforcement is not None:
            rows.append(
                _check("cover", required("slabCover", hours), cover, hours, "Table 4.3.1.1")
            )
    elif kind == "wall":
        rows.append(
            _check(
                "thickness",
                required("wallThickness", hours),
                float(object_type.thickness),
                hours,
                "Table 4.2",
            )
        )
    elif kind in ("beam", "column"):
        profile = getattr(object_type, "profile", None)
        if profile is None:
            return []
        if getattr(profile, "shape", "") == "circle":
            least = 2 * float(profile.radius)
        else:
            least = min(float(profile.xDim), float(profile.yDim))
        main_cover = cover + _transverse_dia(object_type)
        if kind == "column":
            rows.append(
                _check(
                    "least dimension", required("columnSize", hours), least, hours, "Table 4.5.1a"
                )
            )
            need = min(table.columnCoverPerHour * hours, table.columnCoverMax)
            rows.append(_check("cover to the main bars", need, main_cover, hours, "Sec 4.5.3"))
        else:
            width = float(profile.xDim) if hasattr(profile, "xDim") else least
            if width < table.beamWidth:
                rows.append(
                    _check(
                        "width",
                        float(table.beamWidth),
                        width,
                        hours,
                        "Table 4.3.1.2 (narrower beams need the table's larger covers)",
                    )
                )
            rows.append(
                _check(
                    "cover to the main bars",
                    required("beamCover", hours),
                    main_cover,
                    hours,
                    "Table 4.3.1.2",
                )
            )
    return rows


def add_fire_checks(checked: list[dict[str, Any]], types: dict[str, Any], settings: Any) -> int:
    """Adds the fire checks to the designed elements in place (the ratings of ``settings``);
    returns how many elements got them."""
    ratings = getattr(getattr(settings, "analysis", None), "fireResistance", None)
    if ratings is None:
        return 0
    hours_of = {"beam": ratings.beams, "column": ratings.columns, "slab": ratings.slabs,
                "wall": ratings.walls}  # fmt: skip
    count = 0
    for element in checked:
        kind = element.get("kind")
        if kind not in hours_of:
            continue
        rows = member_checks(kind, types.get(element.get("type")), float(hours_of[kind]))
        if not rows:
            continue
        element.setdefault("checks", []).extend(rows)
        failed = [r for r in rows if not r["ok"]]
        if failed:
            element["ok"] = False
            element["utilisation"] = max(
                float(element.get("utilisation", 0.0)), *(r["utilisation"] for r in failed)
            )
        count += 1
    return count
