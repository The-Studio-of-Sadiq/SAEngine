"""BIM curtain wall, glazing and facade feature buttons."""

from __future__ import annotations

from typing import Any

from saengine.features import FeatureContext, feature, number, result, select, table, text
from saengine.features.bim_common import require_bim, write_bim_csv, write_bim_json


@feature(
    "bimAdditionsCurtain.curtainGrid",
    "Curtain Grid",
    part="bim",
    fields=[
        number("width", "Curtain wall width", 12.0, unit="m", min=0.1),
        number("bayWidth", "Bay width", 1.5, unit="m", min=0.1),
        number("storeyHeight", "Storey height", 3.2, unit="m", min=0.1),
    ],
)
def curtain_grid(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates curtain-wall grid spacing."""
    require_bim(ctx)
    bays = max(1, int(values["width"] / values["bayWidth"] + 0.999999))
    return result(
        summary={
            "widthM": values["width"],
            "bayWidthM": values["bayWidth"],
            "bayCount": bays,
            "storeyHeightM": values["storeyHeight"],
        },
        tables=[
            table(
                "Curtain Bays",
                [("bay", "Bay"), ("offsetM", "Offset [m]", "m")],
                [{"bay": i + 1, "offsetM": i * values["bayWidth"]} for i in range(bays)],
            )
        ],
    )


@feature(
    "bimAdditionsCurtain.addMullion",
    "Add Mullion",
    part="bim",
    fields=[
        text("profile", "Mullion profile", "M150"),
        number("height", "Mullion clear span L", 3.6, unit="m", min=0.5),
        number("bayWidthM", "Tributary bay width", 1.5, unit="m", min=0.3),
        number("windKpa", "Design facade wind pressure", 1.5, unit="kPa", min=0.2),
    ],
)
def add_mullion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size curtain-wall mullion required inertia Ixx against L/175 deflection and bending moment."""
    require_bim(ctx)
    L_m = float(values["height"])
    w_kn_m = float(values["windKpa"]) * float(values["bayWidthM"])
    m_knm = w_kn_m * (L_m**2) / 8.0
    delta_lim_mm = (L_m * 1000.0) / 175.0
    # 5 w L^4 / (384 E I) <= delta_lim (E_Al = 70000 MPa = N/mm^2, w in N/mm = kN/m)
    req_ixx_cm4 = ((5.0 * w_kn_m * ((L_m * 1000.0) ** 4)) / (384.0 * 70000.0 * delta_lim_mm)) / 1e4
    row = {
        "profile": values["profile"],
        "spanM": L_m,
        "maxMomentKnM": round(m_knm, 2),
        "deflectionLimitMm": round(delta_lim_mm, 1),
        "requiredIxxCm4": round(req_ixx_cm4, 1),
    }
    path = write_bim_json(ctx, "curtain-mullion.json", row)
    return result(
        summary={**row, "exportPath": path},
        notes=[f"Aluminium E=70 GPa requires Ixx >= {req_ixx_cm4:.1f} cm^4; saved to {path}."],
    )


@feature(
    "bimAdditionsCurtain.gridSegment",
    "Grid Segment",
    part="bim",
    fields=[
        number("start", "Segment start", 0.0, unit="m"),
        number("end", "Segment end", 1.5, unit="m", min=0.1),
    ],
)
def grid_segment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a curtain-grid segment."""
    require_bim(ctx)
    length = abs(values["end"] - values["start"])
    return result(summary={"startM": values["start"], "endM": values["end"], "lengthM": length})


@feature(
    "bimAdditionsCurtain.gridOffset",
    "Grid Offset",
    part="bim",
    fields=[
        number("offset", "Grid offset", 0.1, unit="m"),
        select(
            "direction",
            "Offset direction",
            [("inward", "Inward"), ("outward", "Outward")],
            "outward",
        ),
    ],
)
def grid_offset(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Applies an offset to a curtain grid."""
    require_bim(ctx)
    return result(
        summary={"offsetM": values["offset"]},
        notes=["Offset is a view/model coordinate instruction."],
    )


@feature(
    "bimAdditionsCurtain.gridBoundary",
    "Grid Boundary",
    part="bim",
    fields=[
        number("width", "Boundary width", 12.0, unit="m", min=0.1),
        number("height", "Boundary height", 3.2, unit="m", min=0.1),
    ],
)
def grid_boundary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines the curtain-grid boundary."""
    require_bim(ctx)
    boundary = {
        "widthM": values["width"],
        "heightM": values["height"],
        "areaM2": values["width"] * values["height"],
    }
    path = write_bim_json(ctx, "curtain-grid-boundary.json", boundary)
    return result(summary={**boundary, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.glazingPanel",
    "Glazing Panel",
    part="bim",
    fields=[
        number("width", "Panel width", 1.5, unit="m", min=0.1),
        number("height", "Panel height", 3.0, unit="m", min=0.1),
        number("thickness", "Glass thickness", 24, unit="mm", min=2),
    ],
)
def glazing_panel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a glazing panel specification."""
    require_bim(ctx)
    area = values["width"] * values["height"]
    panel = {
        "widthM": values["width"],
        "heightM": values["height"],
        "thicknessMm": values["thickness"],
        "areaM2": area,
    }
    path = write_bim_json(ctx, "glazing-panel.json", panel)
    return result(summary={**panel, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.spandrelPanel",
    "Spandrel Panel",
    part="bim",
    fields=[
        number("width", "Panel width", 1.5, unit="m", min=0.1),
        number("height", "Panel height", 0.9, unit="m", min=0.1),
        number("thickness", "Panel thickness", 50, unit="mm", min=5),
    ],
)
def spandrel_panel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a spandrel facade panel."""
    require_bim(ctx)
    panel = {
        "widthM": values["width"],
        "heightM": values["height"],
        "thicknessMm": values["thickness"],
        "areaM2": values["width"] * values["height"],
    }
    path = write_bim_json(ctx, "spandrel-panel.json", panel)
    return result(summary={**panel, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.panelSchedule",
    "Panel Schedule",
    part="bim",
    fields=[
        number("bayWidthM", "Standard curtain module width", 1.5, unit="m", min=0.4),
        number("panelCountPerLevel", "Panels per level", 8, unit="ea", min=1, max=200),
        text("prefix", "Panel mark prefix", "CW"),
    ],
)
def panel_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedule facade glazing panels across real BIM stories in 06 BIM/bim.json."""
    data = require_bim(ctx)
    stories = sorted((data.get("stories") or []), key=lambda s: float(s.get("elevation", 0.0)))
    w_m = float(values["bayWidthM"])
    n_per = int(values["panelCountPerLevel"])
    rows = []
    tot_area = 0.0
    if len(stories) >= 2:
        for i in range(len(stories) - 1):
            st = stories[i]
            h_m = max(
                1.0,
                (float(stories[i + 1].get("elevation", 0.0)) - float(st.get("elevation", 0.0)))
                / 1000.0,
            )
            for j in range(n_per):
                area = w_m * h_m
                tot_area += area
                rows.append(
                    {
                        "panel": f"{values['prefix']}-{st.get('id', i + 1)}-{j + 1}",
                        "story": st.get("id", ""),
                        "widthM": w_m,
                        "heightM": round(h_m, 2),
                        "areaM2": round(area, 2),
                    }
                )
    else:
        for j in range(n_per):
            area = w_m * 3.2
            tot_area += area
            rows.append(
                {
                    "panel": f"{values['prefix']}-{j + 1}",
                    "story": "L1",
                    "widthM": w_m,
                    "heightM": 3.2,
                    "areaM2": round(area, 2),
                }
            )
    path = write_bim_csv(
        ctx, "curtain-panel-schedule.csv", ["panel", "story", "widthM", "heightM", "areaM2"], rows
    )
    return result(
        summary={
            "panelCount": len(rows),
            "totalAreaM2": round(tot_area, 1),
            "estGlassKg": round(tot_area * 28.0, 0),
            "exportPath": path,
        },
        tables=[
            table(
                "Facade panel schedule",
                [
                    ("panel", "Mark"),
                    ("story", "Level"),
                    ("widthM", "W", "m"),
                    ("heightM", "H", "m"),
                    ("areaM2", "Area", "m²"),
                ],
                rows[:40],
            )
        ],
        notes=[
            f"Generated from {len(stories)} BIM level(s) (~28 kg/m² DGU weight); exported to {path}."
        ],
    )


@feature(
    "bimAdditionsCurtain.replacePanel",
    "Replace Panel",
    part="bim",
    fields=[
        text("panelId", "Panel mark ID", "CW-BASE-1"),
        select(
            "replacement",
            "Replacement infill",
            [
                ("glazing", "Vision DGU (U=1.8)"),
                ("spandrel", "Insulated Spandrel (U=0.35)"),
                ("vent", "Louvred Vent (U=4.5)"),
            ],
            "glazing",
        ),
        number("panelAreaM2", "Panel surface area", 4.8, unit="m²", min=0.2),
    ],
)
def replace_panel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Update persistent facade panel replacement register with thermal U-value & dead-weight impact."""
    import json

    require_bim(ctx)
    props = {"glazing": (1.8, 28.0), "spandrel": (0.35, 36.0), "vent": (4.5, 22.0)}
    u_val, mass_kg_m2 = props[values["replacement"]]
    area = float(values["panelAreaM2"])
    entry = {
        "panelId": values["panelId"].strip() or "CW-1",
        "replacement": values["replacement"],
        "areaM2": area,
        "uValueWPerM2K": u_val,
        "heatLossWPerK": round(u_val * area, 2),
        "weightKg": round(mass_kg_m2 * area, 1),
    }
    reg = ctx.path("11 Exports/BIM/panel-replacement.json")
    history: list[dict[str, Any]] = []
    if reg is not None and reg.exists():
        try:
            loaded = json.loads(reg.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                history = [r for r in loaded if isinstance(r, dict)]
        except ValueError:
            history = []
    by_id = {str(r.get("panelId", "")): r for r in history}
    by_id[entry["panelId"]] = entry
    rows = list(by_id.values())
    path = write_bim_json(ctx, "panel-replacement.json", rows)
    return result(
        summary={**entry, "registeredOverrides": len(rows), "exportPath": path},
        notes=[
            f"Updated {entry['panelId']} thermal UA={entry['heatLossWPerK']} W/K; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsCurtain.storefrontSystem",
    "Storefront System",
    part="bim",
    fields=[
        number("width", "System width", 6.0, unit="m", min=0.1),
        number("height", "System height", 2.7, unit="m", min=0.1),
        number("mullionSpacing", "Mullion spacing", 1.5, unit="m", min=0.1),
    ],
)
def storefront_system(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a storefront glazing system."""
    require_bim(ctx)
    bays = max(1, int(values["width"] / values["mullionSpacing"] + 0.999999))
    system = {
        "widthM": values["width"],
        "heightM": values["height"],
        "mullionSpacingM": values["mullionSpacing"],
        "bayCount": bays,
    }
    path = write_bim_json(ctx, "storefront-system.json", system)
    return result(summary={**system, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.stickSystem",
    "Stick System",
    part="bim",
    fields=[
        number("width", "Facade width", 12.0, unit="m", min=0.1),
        number("height", "Facade height", 3.2, unit="m", min=0.1),
        number("mullionSpacing", "Mullion spacing", 1.5, unit="m", min=0.1),
    ],
)
def stick_system(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a stick-built curtain-wall system."""
    require_bim(ctx)
    bays = max(1, int(values["width"] / values["mullionSpacing"] + 0.999999))
    system = {
        "widthM": values["width"],
        "heightM": values["height"],
        "mullionSpacingM": values["mullionSpacing"],
        "bayCount": bays,
    }
    path = write_bim_json(ctx, "stick-system.json", system)
    return result(summary={**system, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.unitisedSystem",
    "Unitised System",
    part="bim",
    fields=[
        number("width", "Unit width", 1.5, unit="m", min=0.1),
        number("height", "Unit height", 3.2, unit="m", min=0.1),
        number("quantity", "Unit quantity", 20, unit="ea", min=1),
    ],
)
def unitised_system(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines unitised curtain-wall modules."""
    require_bim(ctx)
    quantity = int(values["quantity"])
    area = values["width"] * values["height"] * quantity
    system = {
        "widthM": values["width"],
        "heightM": values["height"],
        "quantity": quantity,
        "totalAreaM2": area,
    }
    path = write_bim_json(ctx, "unitised-system.json", system)
    return result(summary={**system, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.cornerDetail",
    "Corner Detail",
    part="bim",
    fields=[
        select(
            "corner",
            "Corner type",
            [("miter", "Miter"), ("butt", "Butt"), ("vertical", "Vertical return")],
            "miter",
        ),
        number("angle", "Corner included angle", 90.0, unit="°", min=15.0, max=175.0),
        number("wallDepthMm", "Curtain mullion system depth", 150.0, unit="mm", min=50.0),
    ],
)
def corner_detail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute miter cut bevel angle, bevel leg length, and thermal movement joint at corners."""
    import math

    require_bim(ctx)
    ang = float(values["angle"])
    half_rad = math.radians(ang / 2.0)
    miter_len = float(values["wallDepthMm"]) / max(0.2, math.sin(half_rad))
    thermal_dl_mm = 23e-6 * 1500.0 * 45.0 * 2.0  # 2-wing movement
    detail = {
        "cornerType": values["corner"],
        "angleDeg": ang,
        "cutBevelDeg": round(ang / 2.0, 1),
        "miterCutLengthMm": round(miter_len, 1),
        "minSealantJointMm": round(max(12.0, 2.0 * thermal_dl_mm), 1),
    }
    path = write_bim_json(ctx, "curtain-corner-detail.json", detail)
    return result(
        summary={**detail, "exportPath": path},
        notes=[
            f"Computed corner miter geometry and +/-45 K aluminium expansion joint; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsCurtain.mullionProfile",
    "Mullion Profile",
    part="bim",
    fields=[
        text("profile", "Profile mark", "M150"),
        number("depth", "Profile overall depth", 150.0, unit="mm", min=40.0),
        number("width", "Face width", 60.0, unit="mm", min=25.0),
        number("wallThickMm", "Hollow box wall thickness", 3.5, unit="mm", min=1.5),
    ],
)
def mullion_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute hollow aluminium box-mullion Ix, Sx, area, and extruded mass per metre."""
    require_bim(ctx)
    h = float(values["depth"])
    b = float(values["width"])
    t = min(float(values["wallThickMm"]), 0.4 * min(h, b))
    hi, bi = h - 2.0 * t, b - 2.0 * t
    area_mm2 = b * h - bi * hi
    ix_cm4 = (b * h**3 - bi * hi**3) / 12.0 / 1e4
    sx_cm3 = (ix_cm4 * 1e4 / (h / 2.0)) / 1e3
    mass_kg_m = area_mm2 * 2.70e-3  # 6063-T5/T6 aluminium rho=2700 kg/m3
    profile = {
        "name": values["profile"],
        "depthMm": h,
        "widthMm": b,
        "areaMm2": round(area_mm2, 0),
        "ixCm4": round(ix_cm4, 1),
        "sxCm3": round(sx_cm3, 1),
        "massKgPerM": round(mass_kg_m, 2),
    }
    path = write_bim_json(ctx, "mullion-profile.json", profile)
    return result(
        summary={**profile, "exportPath": path},
        notes=[
            f"Hollow section 6063 Al Ix={ix_cm4:.1f} cm^4 ({mass_kg_m:.2f} kg/m); saved to {path}."
        ],
    )


@feature(
    "bimAdditionsCurtain.cornerMullion",
    "Corner Mullion",
    part="bim",
    fields=[
        text("profile", "Corner mullion mark", "CM200"),
        number("angle", "Corner angle", 90.0, unit="°", min=15.0, max=175.0),
        number("edgeWindKpa", "Facade corner zone suction pressure", 2.1, unit="kPa", min=0.3),
        number("storeyHeightM", "Clear span between floor brackets", 3.6, unit="m", min=1.0),
    ],
)
def corner_mullion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute biaxial corner mullion resultant wind load & required corner moment of inertia."""
    import math

    require_bim(ctx)
    ang_rad = math.radians(float(values["angle"]))
    # Two half-bays (0.75 m each approx) meeting at angle: vector sum scale = 2*cos(ang/2) or hypot
    vec_factor = math.hypot(1.0, math.sin(ang_rad))
    w_kn_m = float(values["edgeWindKpa"]) * 0.75 * vec_factor
    L_mm = float(values["storeyHeightM"]) * 1000.0
    req_ix_cm4 = ((5.0 * w_kn_m * (L_mm**4)) / (384.0 * 70000.0 * (L_mm / 175.0))) / 1e4
    mullion = {
        "profile": values["profile"],
        "angleDeg": float(values["angle"]),
        "resultantLoadKnPerM": round(w_kn_m, 2),
        "requiredInertiaCm4": round(req_ix_cm4, 1),
    }
    path = write_bim_json(ctx, "corner-mullion.json", mullion)
    return result(
        summary={**mullion, "exportPath": path},
        notes=[f"Corner zone resultant Ix_req={req_ix_cm4:.1f} cm^4; saved to {path}."],
    )


@feature(
    "bimAdditionsCurtain.transomProfile",
    "Transom Profile",
    part="bim",
    fields=[
        text("profile", "Transom profile", "T100"),
        number("depth", "Transom depth", 120.0, unit="mm", min=40.0),
        number("width", "Face width", 50.0, unit="mm", min=25.0),
        number("baySpanM", "Mullion-to-mullion transom span", 1.5, unit="m", min=0.5),
        number("panelWeightKg", "Supported DGU panel dead weight", 150.0, unit="kg", min=10.0),
    ],
)
def transom_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check transom vertical gravity deflection under two quarter-point setting-block loads."""
    require_bim(ctx)
    L_mm = float(values["baySpanM"]) * 1000.0
    p_each_n = 0.5 * float(values["panelWeightKg"]) * 9.80665
    a_mm = 0.25 * L_mm
    h, b, t = float(values["depth"]), float(values["width"]), 3.0
    ix_mm4 = (b * h**3 - (b - 2 * t) * (h - 2 * t) ** 3) / 12.0
    iy_mm4 = (h * b**3 - (h - 2 * t) * (b - 2 * t) ** 3) / 12.0
    # Quarter-point vertical dead-load deflection: P*a*(3L^2 - 4a^2)/(24 E Iy_vert? Wait depth h is horizontal for wind, b or wall is vertical!)
    delta_v_mm = (p_each_n * a_mm * (3.0 * L_mm**2 - 4.0 * a_mm**2)) / (24.0 * 70000.0 * iy_mm4)
    profile = {
        "name": values["profile"],
        "depthMm": h,
        "widthMm": b,
        "windIxCm4": round(ix_mm4 / 1e4, 1),
        "deadLoadIyCm4": round(iy_mm4 / 1e4, 1),
        "verticalDeflectionMm": round(delta_v_mm, 2),
        "within2MmLimit": delta_v_mm <= 2.0,
    }
    path = write_bim_json(ctx, "transom-profile.json", profile)
    return result(
        summary={**profile, "exportPath": path},
        notes=[
            f"Vertical glass setting-block deflection={delta_v_mm:.2f} mm (<=2.0 mm prevents glass pinch); saved to {path}."
        ],
    )


@feature(
    "bimAdditionsCurtain.spiderFitting",
    "Spider Fitting",
    part="bim",
    fields=[
        select("arms", "Spider arms", [("2", "2 arms"), ("3", "3 arms"), ("4", "4 arms")], "4"),
        number("diameter", "Bolt PCD fitting diameter", 220.0, unit="mm", min=80.0),
        number("glassAreaM2", "Single glass lite area", 4.5, unit="m²", min=0.5),
        number("windKpa", "Design wind pressure", 1.8, unit="kPa", min=0.2),
    ],
)
def spider_fitting(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate point-fixed stainless spider bolt wind tension & dead-weight shear reaction."""
    import math

    require_bim(ctx)
    arm_reaction_kn = (float(values["glassAreaM2"]) * float(values["windKpa"])) / 4.0
    arm_dead_kn = (
        float(values["glassAreaM2"]) * 38.0 * 9.80665 / 1000.0
    ) / 2.0  # 2 top articulated pins carry dead load
    res_kn = math.hypot(arm_reaction_kn, arm_dead_kn)
    fitting = {
        "arms": values["arms"],
        "diameterMm": float(values["diameter"]),
        "windPerPinKn": round(arm_reaction_kn, 2),
        "deadPerPinKn": round(arm_dead_kn, 2),
        "resultantPinForceKn": round(res_kn, 2),
    }
    path = write_bim_json(ctx, "spider-fitting.json", fitting)
    return result(
        summary={**fitting, "exportPath": path},
        notes=[f"Articulated SS316 pin resultant force={res_kn:.2f} kN; saved to {path}."],
    )


@feature(
    "bimAdditionsCurtain.sunshadeLouver",
    "Sunshade Louver",
    part="bim",
    fields=[
        number("length", "Blade clear span", 1.5, unit="m", min=0.3),
        number("depth", "Blade chord projection depth", 0.30, unit="m", min=0.05),
        number("spacing", "Vertical blade pitch spacing", 0.30, unit="m", min=0.05),
    ],
)
def sunshade_louver(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute exterior solar shading cut-off angle and wind line force per blade."""
    import math

    require_bim(ctx)
    pitch = float(values["spacing"])
    depth = float(values["depth"])
    cutoff_deg = math.degrees(math.atan2(pitch, depth))
    blade_wind_kn = 1.4 * depth * float(values["length"])
    louver = {
        "lengthM": float(values["length"]),
        "depthM": depth,
        "spacingM": pitch,
        "solarCutoffAngleDeg": round(cutoff_deg, 1),
        "bladeWindForceKn": round(blade_wind_kn, 2),
    }
    path = write_bim_json(ctx, "sunshade-louver.json", louver)
    return result(
        summary={**louver, "exportPath": path},
        notes=[f"Blocks all direct solar rays above {cutoff_deg:.1f}° altitude; saved to {path}."],
    )


@feature(
    "bimAdditionsCurtain.structuralSilicone",
    "Structural Silicone",
    part="bim",
    fields=[
        number("thickness", "Proposed silicone bite B", 12.0, unit="mm", min=4.0),
        number("length", "Short glass edge length", 1500.0, unit="mm", min=300.0),
        number("windKpa", "Design negative wind suction", 1.8, unit="kPa", min=0.2),
        number("gluelineMm", "Silicone glueline thickness t_g", 6.0, unit="mm", min=3.0),
    ],
)
def structural_silicone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size structural glazing silicone bite width against trapezoidal wind tributary tension."""
    require_bim(ctx)
    # ETAG 002 / ASTM C1401: B >= (q [kPa] * L_short [mm]) / (2 * f_des [140 kPa])
    f_des_kpa = 140.0
    bite_req = max(6.0, (float(values["windKpa"]) * float(values["length"])) / (2.0 * f_des_kpa))
    ok_bite = float(values["thickness"]) >= bite_req
    ok_glue = float(values["gluelineMm"]) >= 6.0
    joint = {
        "providedBiteMm": float(values["thickness"]),
        "requiredBiteMm": round(bite_req, 1),
        "gluelineMm": float(values["gluelineMm"]),
        "compliant": ok_bite and ok_glue,
    }
    path = write_bim_json(ctx, "structural-silicone.json", joint)
    return result(
        summary={**joint, "exportPath": path},
        notes=[
            f"Uses 140 kPa (0.14 MPa) allowable SSG design tension; required bite={bite_req:.1f} mm; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsCurtain.thermalTransmittance",
    "Thermal Transmittance",
    part="bim",
    fields=[
        number("area", "Facade area", 100.0, unit="m²", min=0.1),
        number("uValue", "Thermal transmittance", 1.8, unit="W/m²K", min=0.1),
        number("temperatureDifference", "Design temperature difference", 20.0, unit="K", min=0),
    ],
)
def thermal_transmittance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculates steady-state facade heat flow."""
    require_bim(ctx)
    heat = values["uValue"] * values["area"] * values["temperatureDifference"]
    return result(
        summary={
            "areaM2": values["area"],
            "uValueWPerM2K": values["uValue"],
            "temperatureDifferenceK": values["temperatureDifference"],
            "heatFlowW": heat,
        },
        notes=["Heat flow uses Q = U A ΔT; it excludes thermal bridges and dynamic effects."],
    )


@feature(
    "bimAdditionsCurtain.deflectionCheck",
    "Deflection Check",
    part="bim",
    fields=[
        number("span", "Mullion span", 3.2, unit="m", min=0.1),
        number("deflection", "Calculated deflection", 12, unit="mm", min=0),
        number("limit", "Deflection limit", 16, unit="mm", min=0.1),
    ],
)
def deflection_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks facade deflection against a limit."""
    require_bim(ctx)
    ratio = values["deflection"] / values["limit"]
    passes = values["deflection"] <= values["limit"]
    return result(
        summary={
            "spanM": values["span"],
            "deflectionMm": values["deflection"],
            "limitMm": values["limit"],
            "utilization": ratio,
            "passes": passes,
        }
    )


@feature(
    "bimAdditionsCurtain.windPressureTest",
    "Wind Pressure Test",
    part="bim",
    fields=[
        number("area", "Panel area", 4.5, unit="m²", min=0.1),
        number("pressure", "Design wind pressure", 1.5, unit="kPa", min=0),
    ],
)
def wind_pressure_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculates wind force on a facade panel."""
    require_bim(ctx)
    force = values["pressure"] * values["area"]
    return result(
        summary={
            "panelAreaM2": values["area"],
            "pressureKpa": values["pressure"],
            "forceKn": force,
        },
        notes=[
            "Design force uses F = pA; pressure must already include the selected design coefficients."
        ],
    )
