"""The earthquake and high wind rules of masonry walls, whatever the design method: the code
pack's ``masonry.seismic`` (the zones it applies in, the materials, the reinforcement of
reinforced walls by zone group, the openings, the strengthening arrangements of the other walls
with their bands and corner bars) and ``masonry.highWind`` (the regions above its wind speed).

:func:`detailing` gives the rows of one wall pier: checks (a required value against the wall's)
and flags (arrangements the drawings must show: bands, corner and jamb bars, roof bracing; the
model has no element for them). A pack without a group does not apply it.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.design import masonry as M
from saengine.design.ductile_members import _row
from saengine.design.rc import bar_area


def _pct(name: str, demand: float, capacity: float, unit: str = "", **kw: Any) -> dict[str, Any]:
    """A ratio row in per cent (the rows round to two decimals)."""
    return _row(name, 100.0 * demand, 100.0 * capacity, "%", **kw)


def _flag(name: str, note: str) -> dict[str, Any]:
    row = _row(name, 0.0, 1.0, "", note=note)
    row["flag"] = True
    return row


def zone_group(zone: int | None) -> str | None:
    """'zone23' or 'zone4' (the highest of the pack's seismic zones), None outside them."""
    zones = list(M.table().seismic.zones)
    if zone is None or zone not in zones:
        return None
    return "zone4" if zone == max(zones) else "zone23"


def strengthening_row(zone: int | None, storeys: int | None) -> Any:
    """The pack's strengthening arrangement row of the zone and the storeys (the first whose
    most storeys covers them), or None."""
    if zone is None:
        return None
    n = storeys or 1
    for row in M.table().seismic.strengthening:
        if zone in row.zones and n <= row.storeysMax:
            return row
    return None


def band_bars(zone: int | None) -> Any:
    bands = M.table().seismic.bands
    if bands is None or zone is None:
        return None
    return next((r for r in bands.rows if zone in r.zones), None)


def corner_bar(
    zone: int | None, storeys: int | None, from_top: int, thickness: float, deformed: bool = True
) -> float | None:
    """The diameter [mm] of the single vertical bar at corners and junctions of the storey
    ``from_top`` (0: the top storey) of a building of ``storeys`` storeys, or the diameter of
    the same area increased in proportion for a wall thicker than the pack's limit; None: none
    needed (or not tabulated)."""
    table = M.table().seismic.cornerBars
    group = zone_group(zone)
    if table is None or group is None or storeys is None:
        return None
    row = next((r for r in table.rows if r.storeys == storeys), None)
    if row is None:
        return None
    dias = (row.deformed if deformed else row.plain).get(group) or []
    if from_top >= len(dias) or dias[from_top] is None:
        return None
    dia = float(dias[from_top])
    if thickness > float(table.thickWall):
        dia = math.sqrt(bar_area(dia) * thickness / float(table.thickWall) * 4.0 / math.pi)
    return dia


def detailing(
    geometry: Any,
    bars: Any,
    m: M.Masonry,
    *,
    zone: int | None = None,
    wind_kmh: float | None = None,
    storeys: int | None = None,
    storey_from_top: int | None = None,
    opening_share: float | None = None,
    bearing: bool = True,
    confined: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The seismic and high wind rows of a wall pier and notes (see the module notes)."""
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    rows += seismic_rows(
        geometry, bars, m, zone, storeys, storey_from_top, opening_share, bearing, confined, notes
    )
    rows += wind_rows(geometry, bars, m, wind_kmh, bearing, notes)
    return rows, notes


def seismic_rows(
    geometry: Any,
    bars: Any,
    m: M.Masonry,
    zone: int | None,
    storeys: int | None,
    storey_from_top: int | None,
    opening_share: float | None,
    bearing: bool,
    confined: bool,
    notes: list[str],
) -> list[dict[str, Any]]:
    s = M.table().seismic
    rows: list[dict[str, Any]] = []
    group = zone_group(zone)
    t = geometry.thickness
    arrangement = strengthening_row(zone, storeys)
    leanest = s.leanestMortar
    if group is not None or (arrangement is not None and "mortar" in arrangement.items):
        rows.append(
            _row(
                f"Mortar not leaner than {leanest} ({M.clause('seismicMaterials')})",
                M.mortar_rank(m.mortar),
                M.mortar_rank(leanest),
                "",
                note=f"mortar {m.mortar or 'of unknown grade'}",
            )
        )
    if group is None:
        return rows
    clause_mat = M.clause("seismicMaterials")
    if m.unit_strength is not None:
        rows.append(
            _row(
                f"Unit strength ≥ {float(s.unitStrengthMin):g} MPa ({clause_mat})",
                float(s.unitStrengthMin),
                m.unit_strength,
                "MPa",
            )
        )
    else:
        notes.append(
            f"unit strength not entered: Zone {zone} needs units of at least "
            f"{float(s.unitStrengthMin):g} MPa ({clause_mat})"
        )
    if bars is not None:
        rows += _reinforced(geometry, bars, m, group, bearing)
    elif not confined:
        rows += _strengthening(zone, storeys, storey_from_top, t, arrangement, notes)
    if opening_share is not None and s.openings is not None:
        o = s.openings
        if opening_share > float(o.maxShare) + 1e-9:
            rows.append(
                _flag(
                    f"Openings ≤ {float(o.maxShare):.0%} of the wall ({M.clause('openings')})",
                    f"openings {opening_share:.0%} of the wall's length: strengthen their jambs "
                    f"({M.clause('jambBars')})",
                )
            )
        notes.append(
            f"openings: at least {float(o.cornerShare[group]):g} × their height from a corner, "
            f"{float(o.betweenShare[group]):g} × the shorter height apart, "
            f"{float(o.verticalGap):g} mm between openings one above the other "
            f"({M.clause('openings')})"
        )
    return rows


def _reinforced(geometry: Any, bars: Any, m: M.Masonry, group: str, bearing: bool):
    s = M.table().seismic
    t = geometry.thickness
    z23, z4 = s.zone23, s.zone4
    c23, c4 = M.clause("zone23"), M.clause("zone4")
    rho_v = bars.rho_l(t)
    rho_h = bars.rho_t(t)
    rows = [
        _row(f"Vertical bars ≥ {float(z23['barMin']):g} mm ({c23})", float(z23["barMin"]),
             bars.vertical_dia, "mm"),
        _row(f"Horizontal bars ≥ {float(z23['barMin']):g} mm ({c23})", float(z23["barMin"]),
             bars.horizontal_dia, "mm"),
        _row(f"Vertical bar spacing ({c23})", bars.vertical_spacing,
             float(z23["verticalSpacing"]), "mm"),
        _row(f"Horizontal bar spacing ({c23})", bars.horizontal_spacing,
             float(z23["horizontalSpacing"]), "mm"),
    ]  # fmt: skip
    if m.bond == "stack":
        rows.append(
            _pct(f"Stack bond ρh ({c23})", float(z23["stackBondRatio"]), rho_h, "",
                 note="Zones 2 and 3")
        )  # fmt: skip
    if group == "zone4":
        rows += [
            _pct(f"ρh + ρv ≥ {float(z4['totalRatio']):g} ({c4})", float(z4["totalRatio"]),
                 rho_h + rho_v, ""),
            _pct(f"ρh ≥ {float(z4['eachRatio']):g} ({c4})", float(z4["eachRatio"]), rho_h, ""),
            _pct(f"ρv ≥ {float(z4['eachRatio']):g} ({c4})", float(z4["eachRatio"]), rho_v, ""),
            _row(f"Bar spacing ≤ {float(z4['maxSpacing']):g} mm ({c4})",
                 max(bars.vertical_spacing, bars.horizontal_spacing), float(z4["maxSpacing"]),
                 "mm"),
            _row(f"Bars ≥ {float(z4['barMin']):g} mm ({c4})", float(z4["barMin"]),
                 min(bars.vertical_dia, bars.horizontal_dia), "mm"),
        ]  # fmt: skip
        if bearing:
            rows.append(
                _row(f"Reinforced bearing wall thickness ({c4})", float(z4["bearingThickness"]),
                     t, "mm")
            )  # fmt: skip
        if m.bond == "stack":
            open_end = m.units == "hollow" and m.grouting == "full"
            need = float(z4["stackBondOpenEndRatio" if open_end else "stackBondRatio"])
            rows.append(
                _pct(f"Stack bond ρh ({c4})", need, rho_h, "",
                     note="open-end units grouted solid" if open_end else "")
            )  # fmt: skip
    return rows


def _strengthening(
    zone: int | None,
    storeys: int | None,
    from_top: int | None,
    t: float,
    arrangement: Any,
    notes: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    clause = M.clause("strengthening")
    if arrangement is None:
        most = max(
            (r.storeysMax for r in M.table().seismic.strengthening if zone in r.zones), default=0
        )
        if most:
            rows.append(
                _row(
                    f"Storeys of plain masonry in Zone {zone} ({clause})",
                    float(storeys or 0),
                    float(most),
                    "",
                    note="the strengthening arrangements cover no more storeys",
                )
            )
        return rows
    items = set(arrangement.items)
    if "bands" in items:
        band = band_bars(zone)
        b = M.table().seismic.bands
        text = (
            f"RC f'c ≥ {float(b.concreteMin):g} MPa, full wall width, depth ≥ "
            f"{float(b.depthMin):g} mm, {band.deformed[0]} - {band.deformed[1]:g} mm deformed "
            f"(or {band.plain[0]} - {band.plain[1]:g} mm plain) bars, {band.link[0]:g} mm links "
            f"at {band.link[1]:g} mm"
            if band is not None and b is not None
            else "see the code"
        )
        rows.append(
            _flag(f"Lintel and roof bands ({M.clause('bands')})", f"provide the bands: {text}")
        )
    if "cornerBars" in items:
        dia = corner_bar(zone, storeys, from_top or 0, t)
        rows.append(
            _flag(
                f"Vertical bars at corners and junctions ({M.clause('cornerBars')})",
                f"one {dia:.0f} mm deformed bar (or the equal area) at each corner and junction, "
                "anchored in the plinth and the roof band, through the lintel bands"
                if dia
                else "none needed in this storey",
            )
        )
    if "jambBars" in items:
        rows.append(
            _flag(
                f"Vertical bars at the jambs of openings ({M.clause('jambBars')})",
                "reinforce the jambs of the openings (RC members or bars in the brickwork)",
            )
        )
    if "roofBracing" in items:
        notes.append(f"pitched roofs: bracing in plan at tie level ({clause})")
    return rows


def wind_rows(
    geometry: Any,
    bars: Any,
    m: M.Masonry,
    wind_kmh: float | None,
    bearing: bool,
    notes: list[str],
) -> list[dict[str, Any]]:
    """The rows of the high wind rules where the basic wind speed exceeds the pack's."""
    w = M.table().highWind
    if w is None or wind_kmh is None or wind_kmh <= float(w.speed):
        return []
    clause = M.clause("highWind")
    rows: list[dict[str, Any]] = []
    t = geometry.thickness
    if m.kind == "clay":
        if m.unit_strength is not None:
            rows.append(
                _row(
                    f"Brick strength ≥ {float(w.unitStrengthMin):g} MPa ({clause})",
                    float(w.unitStrengthMin),
                    m.unit_strength,
                    "MPa",
                )
            )
        else:
            notes.append(
                f"high wind: bricks of at least {float(w.unitStrengthMin):g} MPa ({clause})"
            )
    rows.append(
        _row(
            f"Mortar {' or '.join(w.mortars)} ({clause})",
            0.0 if m.mortar in w.mortars else 1.0,
            1.0,
            "",
            note=f"mortar {m.mortar or 'of unknown grade'}",
            utilisation=0.0 if m.mortar in w.mortars else 99.0,
        )
    )
    if bars is not None:
        kind = "reinforcedBearing"
    elif m.grouting != "none":
        kind = "unreinforcedGrouted"
    else:
        kind = "unreinforced"
    if not bearing:
        kind = "interiorNonbearing"
    least = float(w.minThickness[kind])
    rows.append(
        _row(f"Wall thickness, high wind ({M.clause('highWindThickness')})", least, t, "mm")
    )
    rows.append(
        _row(
            f"Unsupported height ≤ {float(w.maxUnsupportedHeight):g} mm ({clause})",
            geometry.clear_height,
            float(w.maxUnsupportedHeight),
            "mm",
        )
    )
    notes.append(
        f"high wind (> {float(w.speed):g} km/h, {clause}): grout ≥ {float(w.groutStrengthMin):g} "
        f"MPa; footings ≥ {float(w.footingThickness):g} mm thick and "
        f"{float(w.footingDepth):g} mm below ground; lintels ≤ {float(w.lintelSpan):g} mm span "
        f"with bars {float(w.lintelExtension):g} mm past the opening; a continuous tie from the "
        "roof to the foundation; exterior walls ≥ "
        f"{float(w.exteriorWallShare):.0%} of each side in elements ≥ "
        f"{float(w.solidElementMin):g} mm without openings"
    )
    return rows


__all__ = [
    "band_bars",
    "corner_bar",
    "detailing",
    "seismic_rows",
    "strengthening_row",
    "wind_rows",
    "zone_group",
]
