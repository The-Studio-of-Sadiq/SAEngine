"""Footings drawn in the building model, checked with the analysis (Part 8; superseded by Part 9).

The design of footings has moved to Part 9 Substructure: :mod:`saengine.substructure.shallow`
(soil pressure, punching, shear, flexure; the names below are re-exported from it) and
:mod:`saengine.substructure.loads` (the support reactions and the service combinations). This
module keeps :func:`footing_checks`, the design of the ``FootingElement``s of the building model
that Part 8's design report used to run. The report no longer runs it: footings are designed by
Part 9 (:func:`saengine.substructure.substructure_report`), and the drawn footings are moved into
``09 Substructure/substructure.json`` the first time Part 9 or Run All needs them
(:mod:`saengine.substructure.handover`).

Each footing of the building model collects the columns whose base lies inside its plan outline
and takes their support reactions, case by case, as the loads its columns put on it.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from saengine.design.rc import STEEL_E
from saengine.library.bim import BuildingModel, ColumnElement, FootingElement
from saengine.library.materials import Category, MaterialLibrary
from saengine.library.objects import CircleProfile, Column, Footing, ObjectLibrary, RectangleProfile
from saengine.library.settings import ProjectSettings
from saengine.substructure.loads import case_reactions as _case_reactions
from saengine.substructure.loads import column_action, service_combinations
from saengine.substructure.loads import combine as _combine
from saengine.substructure.shallow import (
    Bearing,
    ColumnBase,
    FootingSpec,
    G,
    Loads,
    SoilBearing,
    SoilPressure,
    StripFlexure,
    design_footing,
    gamma_v,
    manual_bearing,
    mesh_area,
    min_steel_ratio,
    one_way_shear_capacity,
    plain_flexure,
    polar_j,
    punching_stress,
    size_factor,
    soil_pressure,
    strip_flexure,
)

__all__ = [
    "FOOTING_METHOD",
    "Bearing",
    "ColumnBase",
    "FootingSpec",
    "G",
    "Loads",
    "SoilBearing",
    "SoilPressure",
    "StripFlexure",
    "column_action",
    "design_footing",
    "footing_checks",
    "gamma_v",
    "manual_bearing",
    "mesh_area",
    "min_steel_ratio",
    "one_way_shear_capacity",
    "plain_flexure",
    "polar_j",
    "punching_stress",
    "service_combinations",
    "size_factor",
    "soil_pressure",
    "strip_flexure",
]

FOOTING_METHOD = [
    (
        "Footings (isolated and combined): the support reactions of the columns standing on "
        "them, reversed, in the footing's axes; a horizontal reaction adds H times the depth "
        "from the column base to the footing's underside. Columns: rectangles as drawn, "
        "circles as the square of the same area (ACI R13.2.7.1)."
    ),
    (
        "Bearing under the allowable-stress combinations of BNBC 2020 Part 6 2.7.2 "
        "(ASCE 7-05 2.4.1) for nominal wind: D, D + L + Lr, D + W, "
        "D + 0.75L + 0.75Lr + 0.75W, 0.6D + W, D + 0.7E, D + 0.75L + 0.75Lr + 0.525E, "
        "0.6D + 0.7E; W and E in ±X and ±Y (with strength-level wind, ASCE 7-16 2.4.1: "
        "0.6W and 0.45W). Gross pressure q = P/A ± Mx/Sx ± My/Sy with the footing's weight "
        "and the soil above it inside the kern; beyond it partial contact, "
        "qmax = 2P / (3 B (L/2 - e)) for one eccentricity and the exact no-tension plane for "
        "two. The net pressure (gross minus γ Df, Df from the ground level to the underside) "
        "is compared with the net allowable bearing pressure qa. Sliding and overturning are "
        "not checked."
    ),
    (
        "qa of each footing: the override of Project Settings → Foundation when it is given; "
        "otherwise, when 1 Soil Report has boreholes, its net allowable pressure for that "
        "footing (saengine.soil.allowable_bearing): the lowest of the boreholes within 10 m of "
        "the footing's centre (else the nearest; none when one of them gives none), for its "
        "B × L at its founding level (Df from the borehole's ground level); each footing's "
        "check says where its qa came from. That qa is net of the overburden at the founding "
        "level below the borehole's ground: the net pressure then takes off that overburden "
        "(or γ Df below the finished ground when it is less), so fill above the borehole's "
        "ground stays a load."
    ),
    (
        "Footing strength under the factored combinations: soil pressure under the column "
        "loads and the factored weight of the footing and the soil above it, that weight "
        "acting down (the net factored pressure while the whole base is in contact). One-way "
        "shear at d from the column faces (ACI 13.2.7.2, Vc = 0.66 λs ρw^(1/3) √f'c b d <= "
        "0.42 √f'c b d, Table 22.5.5.1, ρw of the bottom mesh), punching at d/2 around each "
        "column (ACI 22.6.5.2: least of 0.33, 0.17 (1 + 2/β) and 0.083 (2 + αs d / b0) times "
        "λs √f'c, φ = 0.75) with γv Mu c / Jc for the column base moments about both axes "
        "(ACI 8.4.4.2.3; Jc of the full rectangle also for edge and corner sections), flexure "
        "at the column faces (ACI 13.2.7.1) against the bottom mesh, and top flexure where the "
        "footing hogs (between the columns of a combined footing, or where the weight of the "
        "footing and the soil exceeds the soil pressure) against the top mesh, or as plain "
        "concrete without one (ACI 14.5.2.1, h - 50 mm per 14.5.1.7). The "
        "footing is a beam in each direction under the soil pressure, its weight and the "
        "column loads spread over the column widths; isolated footings over their full width. "
        "Combined footings across their length: a transverse strip of width c + d under each "
        "column carrying that column's load (ACI 336.2R practice), for flexure and one-way "
        "shear. λs (22.5.5.1.3) is applied although ACI 13.2.6.2 permits neglecting it for "
        "footings. Effective depths to the centroid of each direction's bars (ACI 2.2), the X "
        "bars the outer layer and the Y bars on them, as in slabs: dX = thickness - cover - "
        "dbX/2, dY = thickness - cover - dbX - dbY/2 (the top mesh likewise from the top "
        "face); flexure and one-way shear in each direction take its own layer's d, punching "
        "and the transverse strips the mean of the two (ACI 22.6.2.1). Minimum reinforcement "
        "0.0018 Ag (ACI 7.6.1.1). Development lengths are not checked."
    ),
]


def footing_checks(
    project: dict[str, Any],
    out_dir: str | Path,
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary,
    settings: ProjectSettings,
    soil_text: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """The footing checks of an analysed model, in :func:`saengine.design.design_report`'s
    format: ``(elements, skipped, notes)``. Arguments as :func:`saengine.design.check.design`;
    ``soil_text`` is the soil report's text: when it has boreholes, each footing's qa comes
    from it at the footing's position, founding level and size (:class:`SoilBearing`), unless
    Project Settings → Foundation gives the override.
    """
    from saengine.fem.combinations import combination_factors

    footings = [e for e in building.elements if isinstance(e, FootingElement)]
    if not footings:
        return [], [], []
    soil = SoilBearing(soil_text, settings.foundation)
    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in materials.materials}
    by_case = _case_reactions(out_dir)

    # Restrained nodes of the analysis model, by position [mm].
    supports: dict[tuple[int, int, int], int] = {}
    for node in project.get("nodes", []):
        if any(node.get("restraint") or []):
            key = tuple(round(float(c) * 1000) for c in node["coords"][:3])
            supports[key] = int(node["id"])  # type: ignore[index]
    bases: list[tuple[ColumnElement, int]] = []
    for element in building.elements:
        if isinstance(element, ColumnElement):
            key = (round(element.position[0]), round(element.position[1]), round(element.bottom))
            if key in supports:
                bases.append((element, supports[key]))

    strength: list[tuple[str, dict[str, float]]] = []
    for combination in settings.combinations:
        factors = combination_factors(combination, set(by_case))
        if all(case in by_case for case in factors):
            strength.append((combination.name, factors))
    # Wind is nominal when a strength combination factors it above 1.0 (1.6W, BNBC 2.7.3).
    wind_factors = [abs(f) for _, fs in strength for case, f in fs.items() if case[:1] == "W"]
    strength_level_wind = bool(wind_factors) and max(wind_factors) <= 1.0 + 1e-9
    service = service_combinations(by_case, strength_level_wind)
    dead = {name: factors.get("D", factors.get("SD", 0.0)) for name, factors in strength}

    elements: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    notes: list[str] = []
    placed: set[str] = set()
    for footing in footings:
        object_type = types.get(footing.type)

        def skip(reason: str, footing: FootingElement = footing) -> None:
            skipped.append(
                {"id": footing.id, "kind": "footing", "type": footing.type, "reason": reason}
            )

        if object_type is None:
            skip(f"unknown object type '{footing.type}'")
            continue
        if not isinstance(object_type, Footing):
            skip(f"{object_type.kind} foundations are not designed yet")
            continue
        theta = math.radians(footing.rotation)
        axis_u = np.array([math.cos(theta), math.sin(theta), 0.0])
        axis_v = np.array([-math.sin(theta), math.cos(theta), 0.0])
        bottom = footing.elevation - object_type.thickness
        on: list[tuple[ColumnElement, int, float, float]] = []
        for column, node in bases:
            offset = np.array(
                [
                    column.position[0] - footing.position[0],
                    column.position[1] - footing.position[1],
                    0,
                ]
            )
            u, v = float(offset @ axis_u), float(offset @ axis_v)
            if abs(u) <= object_type.length / 2 + 1 and abs(v) <= object_type.width / 2 + 1:
                if column.id in placed:
                    notes.append(
                        f"{column.id}: stands on more than one footing; taken by the first"
                    )
                    continue
                on.append((column, node, u, v))
        if object_type.footingType == "strip":
            skip("strip footings are not designed yet")
            placed.update(c.id for c, *_ in on)
            continue
        if not on:
            skip("no column base lies within its plan outline")
            continue
        placed.update(c.id for c, *_ in on)
        concrete = mats.get(object_type.material)
        if concrete is None or concrete.category != Category.CONCRETE or not concrete.concrete:
            skip("not a concrete footing")
            continue
        reinforcement = object_type.reinforcement
        if reinforcement is None:
            skip("no reinforcement")
            continue
        bars = mats.get(reinforcement.material)
        if bars is None or bars.steel is None:
            skip(f"unknown reinforcement material '{reinforcement.material}'")
            continue
        if not strength:
            skip("no load combination could be formed")
            continue
        spec_notes: list[str] = []
        columns: list[ColumnBase] = []
        problem = None
        for column, _, u, v in on:
            column_type = types.get(column.type)
            profile = column_type.profile if isinstance(column_type, Column) else None
            if isinstance(profile, RectangleProfile):
                sides = (profile.xDim, profile.yDim)
            elif isinstance(profile, CircleProfile):
                side = profile.radius * math.sqrt(math.pi)
                sides = (side, side)
            else:
                problem = f"{column.id}: only rectangular and circular columns are supported"
                break
            turn = (column.rotation - footing.rotation) / 90
            if abs(turn - round(turn)) > 1e-6 and not isinstance(profile, CircleProfile):
                spec_notes.append(
                    f"{footing.id}: {column.id} is skewed to the footing; taken at the nearest "
                    "quarter turn"
                )
            if round(turn) % 2:
                sides = sides[::-1]
            columns.append(
                ColumnBase(column.id, u, v, sides[0], sides[1], max(column.bottom - bottom, 0.0))
            )
        if problem:
            skip(problem)
            continue
        if object_type.footingType == "isolated" and len(columns) > 1:
            spec_notes.append(
                f"{footing.id}: an isolated footing under {len(columns)} columns is designed as "
                "a combined footing"
            )
        density = concrete.mechanical.density or 2400.0
        spec = FootingSpec(
            id=footing.id,
            type=footing.type,
            footing_type=object_type.footingType,
            length=object_type.length,
            width=object_type.width,
            thickness=object_type.thickness,
            elevation=footing.elevation,
            cover=reinforcement.cover,
            fc=concrete.concrete.fc,
            fy=bars.steel.fy,
            es=bars.mechanical.E or STEEL_E,
            columns=columns,
            bottom_x=reinforcement.bottomX,
            bottom_y=reinforcement.bottomY,
            top_x=reinforcement.topX,
            top_y=reinforcement.topY,
            unit_weight=density * G * 1e-9,
        )
        if min(spec.depths("bottom").values()) <= 0:
            skip("the cover and bars leave no effective depth")
            continue

        per_case = {
            case: [
                column_action(reactions.get(node, np.zeros(6)), c.arm, axis_u, axis_v)
                for (_, node, _, _), c in zip(on, columns, strict=True)
            ]
            for case, reactions in by_case.items()
        }
        checks, footing_notes = design_footing(
            spec,
            {name: _combine(per_case, factors) for name, factors in service},
            {name: _combine(per_case, factors) for name, factors in strength},
            settings.foundation,
            dead,
            soil.at(
                footing.position[0],
                footing.position[1],
                bottom,
                object_type.width,
                object_type.length,
            ),
        )
        notes += spec_notes + footing_notes
        strength_checks = [c for c in checks if not c["flag"]]
        elements.append(
            {
                "id": footing.id,
                "kind": "footing",
                "type": footing.type,
                "members": [c.id for c in columns],
                "checks": checks,
                "utilisation": max((c["utilisation"] for c in strength_checks), default=0.0),
                "ok": all(c["ok"] for c in strength_checks),
            }
        )
    for column, _ in bases:
        if column.id not in placed:
            notes.append(f"{column.id}: no footing under it")
    if elements:
        notes += soil.notes()
    return elements, skipped, notes
