"""The two-level seismic design of codes that design for a frequent earthquake and check a rare
one (alpha 9 C20, the GB 50011-2010 type), and the seismic grades that drive the detailing.

A pack opts in with ``seismic.rareDrift`` and ``seismic.seismicGrades`` (empty in every other
pack: nothing here runs and the seismic design summary is unchanged).

- **Elasto-plastic drift under the rare earthquake** (``rareDrift``, method
  ``amplifiedElastic``, the simplified method of GB 50011 5.5.3-5.5.4): the elastic storey drift
  under the rare earthquake Δue = the frequent earthquake's storey drift (the response spectrum
  drift rows of :func:`saengine.fem.seismic_design.storey_drifts`, as computed) × α_rare(T1) /
  α(T1) of the pack's ``influenceCoefficient`` spectrum (T1 the direction's longest modal
  period); Δup = ηp Δue with ηp of the first ``amplification`` row of the system's group and
  storey count at the yield strength coefficient ξy (``yieldStrengthRatio``, one value for
  every storey: a project's Code Value); Δup / h at most [θp] of the system's group. The check
  by a pushover (P3) or a nonlinear time history (P5) under the rare earthquake replaces it
  where the engineer runs them (the notes say so).
- **Seismic grades** (``seismicGrades``, GB 50011 Table 6.1.2 type): the intensity column of
  the site's zone, raised for the occupancy categories that take the measures of a higher
  intensity, the first row of the system's group whose height holds, its grade with the
  detailing level and the design factors the pack gives (strong column ηc, shear ηv, the axial
  compression ratio limit ...), reported with the seismic design.

Pure functions of the results and the pack in force.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from saengine.codes import context as code_context


def _seismic() -> Any:
    return code_context.table("seismic")


def _along(points: list[Any], x: float) -> float:
    pts = sorted((float(a), float(b)) for a, b in points)
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in pairwise(pts):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y1
    return pts[-1][1]


def _group(system: str) -> str | None:
    entry = _seismic().systems.get(system)
    return entry.group if entry is not None else None


def amplification(rule: Any, group: str | None, storeys: int, xi_y: float) -> tuple[float, str]:
    """(ηp, the row's label) of the first ``amplification`` row whose groups hold ``group`` and
    whose ``maxStoreys`` holds ``storeys``; the rule's default without one."""
    for row in rule.amplification:
        if row.groups is not None and group not in row.groups:
            continue
        if row.maxStoreys is not None and storeys > row.maxStoreys:
            continue
        return _along(list(row.points), xi_y), row.label
    return float(rule.defaultAmplification), "other structures"


def plastic_limit(rule: Any, group: str | None) -> tuple[float, str]:
    """([θp], its label) of the system's group."""
    for row in rule.limits:
        if row.groups is None or group in row.groups:
            return float(row.limit), row.label
    return float(rule.defaultLimit), "other structures"


def _longest_period(data: dict[str, Any]) -> float | None:
    import math

    periods = [
        2 * math.pi / float(m["angular_frequency"])
        for m in data.get("modes", [])
        if float(m.get("angular_frequency") or 0.0) > 0
    ]
    return max(periods) if periods else None


def rare_drift(
    drift: list[dict[str, Any]],
    spectra: dict[str, dict[str, Any]],
    settings: Any,
    zone: int | None,
    z: Any,
    storeys: int,
) -> dict[str, Any] | None:
    """The elasto-plastic storey drift check (see the module notes): ``{"rows", "ok",
    "yieldStrengthRatio", "amplification", "limit", "clause", "notes"}``; None when the pack has
    no ``rareDrift`` rule or no influence coefficient spectrum, or the zone is not checked."""
    rule = getattr(_seismic(), "rareDrift", None)
    spectrum = getattr(_seismic(), "designSpectrum", None)
    influence = getattr(spectrum, "influence", None) if spectrum is not None else None
    if rule is None or influence is None or zone is None:
        return None
    from saengine.fem.spectra import rare_ratio

    zones = rule.zones or list(influence.rare)
    if int(zone) not in [int(k) for k in zones]:
        return None
    try:
        z_value = float(z)
    except (TypeError, ValueError):
        return None
    site = _seismic().siteClasses.get(settings.site.siteClass)
    if site is None:
        return None
    group = _group(settings.seismic.system)
    xi_y = float(rule.yieldStrengthRatio)
    eta_p, eta_label = amplification(rule, group, storeys, xi_y)
    limit, limit_label = plastic_limit(rule, group)
    notes: list[str] = []
    ratios: dict[str, float] = {}
    for axis, data in spectra.items():
        period = _longest_period(data)
        if period is None:
            continue
        ratio = rare_ratio(period, site.TC, zone, z_value, settings.seismic.damping, influence)
        if ratio is not None:
            ratios[axis] = ratio
            notes.append(
                f"{axis}: rare earthquake α_rare(T1) / α(T1) = {ratio:.3f} at T1 = {period:.3f} s"
            )
    rows = []
    for d in drift:
        ratio = ratios.get(d["direction"])
        if ratio is None or not d.get("height"):
            continue
        elastic = float(d["designDrift"]) * ratio
        plastic = eta_p * elastic
        rows.append(
            {
                "direction": d["direction"],
                "bottom": d["bottom"],
                "top": d["top"],
                "height": d["height"],
                "frequentDrift": float(d["designDrift"]),
                "rareElasticDrift": elastic,
                "plasticDrift": plastic,
                "ratio": plastic / float(d["height"]),
                "allowableRatio": limit,
                "ok": bool(plastic / float(d["height"]) <= limit + 1e-12),
            }
        )
    if not rows:
        return None
    clause = rule.clause
    notes.append(
        f"elasto-plastic storey drift under the rare earthquake by the simplified method: Δup "
        f"= ηp Δue, ηp = {eta_p:.2f} ({eta_label}, ξy = {xi_y:g} taken for every storey: set "
        f"the Code Value seismic.rareDrift.yieldStrengthRatio from the storeys' yield shears), "
        f"[θp] = 1/{1 / limit:.0f} ({limit_label})" + (f" ({clause})" if clause else "")
    )
    notes.append(
        "a pushover (Analysis > Pushover) or nonlinear time histories under the rare "
        "earthquake check the same drift without the simplified method's limits of use"
    )
    return {
        "rows": rows,
        "ok": all(r["ok"] for r in rows),
        "yieldStrengthRatio": xi_y,
        "amplification": eta_p,
        "limit": limit,
        "clause": clause,
        "notes": notes,
    }


def seismic_grade(
    system: str, height: float, zone: int | None, occupancy: str
) -> dict[str, Any] | None:
    """The seismic grade of the structure (see the module notes): ``{"grade", "label",
    "level", "factors", "column", "clause"}``; None without the pack's ``seismicGrades``, a
    zone, the system's group in a row or a grade in the column."""
    rule = getattr(_seismic(), "seismicGrades", None)
    if rule is None or zone is None:
        return None
    column = rule.columns.get(int(zone))
    if column is None or column not in rule.order:
        return None
    raised = int(rule.raise_.get(occupancy, 0))
    index = min(rule.order.index(column) + raised, len(rule.order) - 1)
    column = rule.order[index]
    group = _group(system)
    for row in rule.rows:
        if group not in row.groups:
            continue
        if row.maxHeight is not None and height > row.maxHeight + 1e-9:
            continue
        grade_id = row.grades.get(column)
        grade = rule.grades.get(grade_id) if grade_id is not None else None
        if grade is None:
            return None
        return {
            "grade": grade_id,
            "label": grade.label,
            "level": grade.level,
            "factors": dict(grade.factors),
            "column": column,
            "raised": raised,
            "clause": rule.clause,
        }
    return None


def grade_note(found: dict[str, Any]) -> str:
    """The note of a :func:`seismic_grade` result."""
    factors = ", ".join(f"{k} {v:g}" for k, v in found["factors"].items())
    raised = f", measures raised {found['raised']} intensity step(s)" if found["raised"] else ""
    clause = f" ({found['clause']})" if found["clause"] else ""
    return (
        f"seismic grade {found['label']} (intensity column {found['column']}{raised}): "
        f"detailing level {found['level']}" + (f"; {factors}" if factors else "") + clause
    )


def summary_block(
    settings: Any,
    values: dict[str, Any],
    drift: list[dict[str, Any]],
    spectra: dict[str, dict[str, Any]],
    storeys: list[float],
    notes: list[str],
) -> dict[str, Any]:
    """The keys this module adds to the seismic design summary (``rareDrift``,
    ``seismicGrade``), {} for a pack with neither rule; their notes go into ``notes``."""
    table = _seismic()
    if getattr(table, "rareDrift", None) is None and getattr(table, "seismicGrades", None) is None:
        return {}
    from saengine.fem.seismic_design import zone_of

    z = values.get("Z")
    zone = values.get("zone")
    if zone is None and isinstance(z, int | float):
        zone = zone_of(z)
    out: dict[str, Any] = {}
    count = max(len(storeys) - 1, 0)
    found = rare_drift(drift, spectra, settings, zone, z, count)
    if found is not None:
        out["rareDrift"] = found
        notes.extend(found["notes"])
        failing = [r for r in found["rows"] if not r["ok"]]
        if failing:
            worst = max(failing, key=lambda r: r["ratio"])
            notes.append(
                f"{worst['direction']}: the elasto-plastic storey drift under the rare "
                f"earthquake {100 * worst['ratio']:.2f} % between {worst['bottom']:g} and "
                f"{worst['top']:g} m exceeds {100 * found['limit']:.2f} %"
            )
    height = storeys[-1] - storeys[0] if len(storeys) > 1 else 0.0
    grade = seismic_grade(settings.seismic.system, height, zone, settings.occupancy.category)
    if grade is not None:
        out["seismicGrade"] = grade
        notes.append(grade_note(grade))
    return out
