"""Soil Report - Earth Pressure & Chemistry tab: lateral earth pressure profiles.

Soil mechanics (Rankine, Jaky), not code values: the code pack asks for the lateral soil
pressure without prescribing the theory.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.features import FeatureContext, FeatureInputError, feature, number, result, table
from saengine.soil.earth_pressure import rankine_active, rankine_passive

_COMMON = [
    number("height", "Retained height", 4.0, unit="m", min=0.1),
    number("gamma", "Soil unit weight", 18.0, unit="kN/m³", min=1),
    number("phi", "Friction angle φ'", 30.0, unit="°", min=0, max=50),
    number("cohesion", "Effective cohesion c'", 0.0, unit="kPa", min=0),
    number(
        "water",
        "Water table below top",
        100.0,
        unit="m",
        min=0,
        help="Deeper than the wall: no water.",
    ),
    number("surcharge", "Uniform surcharge", 10.0, unit="kPa", min=0),
]
GAMMA_W = 9.81


def _profile(
    values: dict[str, Any], k: float, sign: int
) -> tuple[list[dict[str, Any]], float, float]:
    """The pressure at depth steps: effective k·σv' -/+ 2c√k, plus water; the resultant and its
    height above the base. ``sign`` -1 for active (cohesion reduces), +1 for passive."""
    h, gamma, c, zw, q = (
        values[k_] for k_ in ("height", "gamma", "cohesion", "water", "surcharge")
    )
    steps = 20
    rows = []
    points = []
    for i in range(steps + 1):
        z = h * i / steps
        u = GAMMA_W * max(0.0, z - zw)
        sigma_v = q + gamma * z - u
        p_soil = (
            max(0.0, k * sigma_v + sign * 2 * c * math.sqrt(k))
            if sign < 0
            else k * sigma_v + 2 * c * math.sqrt(k)
        )
        p = p_soil + u
        points.append((z, p))
        if i % 4 == 0:
            rows.append(
                {"depth": round(z, 2), "sigmaV": sigma_v, "soil": p_soil, "water": u, "total": p}
            )
    force = sum(
        (points[i + 1][0] - points[i][0]) * (points[i][1] + points[i + 1][1]) / 2
        for i in range(steps)
    )
    moment = sum(
        (points[i + 1][0] - points[i][0])
        * (points[i][1] + points[i + 1][1])
        / 2
        * (h - (points[i][0] + points[i + 1][0]) / 2)
        for i in range(steps)
    )
    return rows, force, (moment / force if force > 0 else 0.0)


def _pressure_result(
    values: dict[str, Any], name: str, k: float, sign: int, note: str
) -> dict[str, Any]:
    rows, force, arm = _profile(values, k, sign)
    return result(
        summary={"coefficient": k, "resultantKnPerM": force, "actsAboveBaseM": arm},
        tables=[
            table(
                f"{name} pressure with depth",
                [
                    ("depth", "Depth", "m"),
                    ("sigmaV", "σv'", "kPa"),
                    ("soil", "Soil pressure", "kPa"),
                    ("water", "Water", "kPa"),
                    ("total", "Total", "kPa"),
                ],
                rows,
            )
        ],
        notes=[note, "Per metre run of wall; a level backfill against a smooth vertical back."],
    )


@feature(
    "soilEarth.atRestPressure",
    "At-Rest Earth Pressure",
    part="soil",
    fields=_COMMON,
    requires_project=False,
)
def at_rest(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """At-rest pressure of a wall that does not move (basement walls, propped walls, tanks)."""
    k0 = 1 - math.sin(math.radians(values["phi"]))
    return _pressure_result(
        values, "At-rest", k0, -1, "K0 = 1 - sin φ' (Jaky), normally consolidated soil."
    )


@feature(
    "soilEarth.activePressure",
    "Active Earth Pressure",
    part="soil",
    fields=_COMMON,
    requires_project=False,
)
def active(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Active pressure of a wall free to move away from the soil (cantilever retaining walls)."""
    ka = rankine_active(values["phi"])
    return _pressure_result(
        values, "Active", ka, -1, "Ka = tan²(45° - φ'/2) (Rankine); tension from c' is ignored."
    )


@feature(
    "soilEarth.passivePressure",
    "Passive Earth Pressure",
    part="soil",
    fields=_COMMON,
    requires_project=False,
)
def passive(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Passive resistance of soil pushed by the wall (toe resistance, anchor blocks)."""
    kp = rankine_passive(values["phi"])
    return _pressure_result(
        values,
        "Passive",
        kp,
        1,
        "Kp = tan²(45° + φ'/2) (Rankine); mobilising it needs large movement: apply a factor.",
    )


@feature(
    "soilEarth.surchargePressure",
    "Surcharge Pressure",
    part="soil",
    fields=[
        number("height", "Wall height", 4.0, unit="m", min=0.1),
        number("load", "Strip load", 20.0, unit="kPa", min=0),
        number("offset", "Distance from wall to load", 1.0, unit="m", min=0),
        number("width", "Load width", 2.0, unit="m", min=0.1),
    ],
    requires_project=False,
)
def surcharge(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Lateral pressure on a rigid wall from a strip load behind it (elastic, Boussinesq doubled)."""
    h, q, a, w = values["height"], values["load"], values["offset"], values["width"]
    rows = []
    pts = []
    for i in range(21):
        z = max(1e-6, h * i / 20)
        a1 = math.atan(a / z)
        a2 = math.atan((a + w) / z)
        beta = a2 - a1
        alpha = a1 + beta / 2
        sigma = 2 * q / math.pi * (beta - math.sin(beta) * math.cos(2 * alpha))
        pts.append((z, sigma))
        if i % 4 == 0:
            rows.append({"depth": round(h * i / 20, 2), "pressure": sigma})
    force = sum((pts[i + 1][0] - pts[i][0]) * (pts[i][1] + pts[i + 1][1]) / 2 for i in range(20))
    return result(
        summary={"resultantKnPerM": force, "maxPressureKpa": max(p for _, p in pts)},
        tables=[
            table(
                "Lateral pressure from the strip load",
                [("depth", "Depth", "m"), ("pressure", "Pressure", "kPa")],
                rows,
            )
        ],
        notes=[
            "Strip load parallel to the wall; the elastic solution is doubled for a rigid, unyielding wall."
        ],
    )


@feature(
    "soilBearing.ultimateBearing",
    "Ultimate Bearing Capacity",
    part="soil",
    fields=[
        number("width", "Footing width B", 2.0, unit="m", min=0.1),
        number("length", "Footing length L", 2.0, unit="m", min=0.1),
        number("depth", "Founding depth Df", 1.5, unit="m", min=0),
        number("cohesion", "Cohesion c", 0.0, unit="kPa", min=0),
        number("phi", "Friction angle φ", 30.0, unit="°", min=0, max=50),
        number("gamma", "Unit weight γ", 18.0, unit="kN/m³", min=1),
        number("fs", "Factor of safety", 3.0, min=1),
    ],
    requires_project=False,
)
def ultimate_bearing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """The general bearing capacity equation for a footing, with its factors and the allowable pressure."""
    from saengine.report.clauses import in_force
    from saengine.soil import bearing

    b, l_, df = values["width"], values["length"], values["depth"]
    if values["fs"] <= 0:
        raise FeatureInputError("The factor of safety must be positive.")
    with in_force(ctx.root):
        out = bearing.ultimate(
            values["cohesion"], values["phi"], values["gamma"] * df, values["gamma"], b, l_, df
        )
    qu = out["qu"]
    rows = [{"term": k, "value": v} for k, v in out.items() if k != "qu"]
    return result(
        summary={
            "ultimateKpa": qu,
            "allowableKpa": (qu - values["gamma"] * df) / values["fs"] + values["gamma"] * df,
        },
        tables=[table("Bearing capacity factors", [("term", "Term"), ("value", "Value")], rows)],
        notes=[
            "Allowable = net ultimate / FS + overburden. Check settlement separately (Settlement tab)."
        ],
    )
