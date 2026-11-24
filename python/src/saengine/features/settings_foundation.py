"""Project Settings - Foundation Defaults tab: bearing, springs, groundwater, detailing, subgrade, waterproofing, construction."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.settings_common import active_pack, load_settings, safe_table
from saengine.report.clauses import in_force
from saengine.soil import bearing as soil_bearing
from saengine.soil.profile import Profile


@feature(
    "settingsFoundation.defaultBearing",
    "Default Bearing",
    part="settings",
    fields=[
        number("footingWidthM", "Reference footing width B", 2.0, unit="m", min=0.4),
        number("foundingDepthM", "Reference founding depth Df", 1.5, unit="m", min=0.3),
    ],
    requires_project=False,
)
def default_bearing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate default allowable bearing from project settings override or soil report boreholes."""
    st = load_settings(ctx)
    rep = ctx.soil()
    qa_override = st.foundation.allowableBearing
    rows = []
    if rep is not None and rep.boreholes:
        with in_force(ctx.root, st):
            for bh in rep.boreholes[:6]:
                prof = Profile(rep, bh)
                res = soil_bearing.allowable(
                    prof, values["footingWidthM"], values["footingWidthM"], values["foundingDepthM"]
                )
                rows.append(
                    {
                        "source": bh.id,
                        "qaKpa": res.get("qa") or 0.0,
                        "governs": str(res.get("governs") or "-"),
                    }
                )
    qa_eff = float(qa_override) if qa_override else (rows[0]["qaKpa"] if rows else 150.0)
    return result(
        summary={
            "effectiveQaKpa": qa_eff,
            "overrideActive": qa_override is not None,
            "boreholesChecked": len(rows),
        },
        tables=[
            table(
                "Allowable bearing summary",
                [("source", "Source"), ("qaKpa", "qa", "kPa"), ("governs", "Governing mode")],
                rows
                or [{"source": "Default/Override", "qaKpa": qa_eff, "governs": "User setting"}],
            )
        ],
        notes=[
            "Uses foundation.allowableBearing override when set, otherwise evaluates 1 Soil Report boreholes."
        ],
    )


@feature(
    "settingsFoundation.soilSpringDefault",
    "Soil Spring Default",
    part="settings",
    fields=[
        number("qaKpa", "Allowable bearing pressure qa", 180.0, unit="kPa", min=20.0),
        number("settLimitMm", "Reference settlement δ", 25.0, unit="mm", min=5.0),
        number("factorOfSafety", "Bearing factor of safety", 2.5, min=1.5, max=5.0),
    ],
    requires_project=False,
)
def soil_spring_default(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate vertical Winkler subgrade modulus ks using Bowles bearing-settlement correlation."""
    ks_kpa_m = values["qaKpa"] * values["factorOfSafety"] / (values["settLimitMm"] / 1000.0)
    # Direct ratio qa / delta
    ks_direct = values["qaKpa"] / (values["settLimitMm"] / 1000.0)
    rows = [
        {"method": "Direct secant (qa / δ)", "ksKnPerM3": ks_direct},
        {"method": "Bowles estimate (FS × qa / δ)", "ksKnPerM3": ks_kpa_m},
    ]
    return result(
        summary={"secantKsKnPerM3": ks_direct, "bowlesKsKnPerM3": ks_kpa_m},
        tables=[
            table(
                "Default Winkler subgrade modulus ks",
                [("method", "Basis"), ("ksKnPerM3", "ks", "kN/m³")],
                rows,
            )
        ],
        notes=["Bowles correlation ks = FS × qa / δ provides initial Winkler spring stiffness."],
    )


@feature(
    "settingsFoundation.groundWaterDefault",
    "Ground Water Default",
    part="settings",
    fields=[
        number("gwtDepthM", "Groundwater table depth below ground", 3.0, unit="m", min=0.0),
        number("footingDepthM", "Foundation depth Df", 2.0, unit="m", min=0.3),
        number("basementDepthM", "Basement slab depth", 4.0, unit="m", min=0.0),
    ],
    requires_project=False,
)
def ground_water_default(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check groundwater table depth from soil report and compute hydrostatic uplift pressure."""
    rep = ctx.soil()
    gwt = values["gwtDepthM"]
    if rep is not None and rep.boreholes:
        depths = [b.waterTable for b in rep.boreholes if b.waterTable is not None]
        if depths:
            gwt = min(depths)
    uplift_kpa = max(0.0, values["basementDepthM"] - gwt) * 9.81
    submerged = values["footingDepthM"] > gwt
    return result(
        summary={"gwtDepthM": gwt, "footingSubmerged": submerged, "basementUpliftKpa": uplift_kpa},
        tables=[
            table(
                "Groundwater table impact",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Governing GWT depth [m]", "value": gwt},
                    {"item": "Footing below GWT", "value": str(submerged)},
                    {"item": "Basement uplift [kPa]", "value": uplift_kpa},
                ],
            )
        ],
        notes=["Uses shallowest borehole waterDepth from 1 Soil Report when available."],
    )


@feature(
    "settingsFoundation.footingDefaults",
    "Footing Defaults",
    part="settings",
    fields=[
        number("minThicknessMm", "Minimum pad footing thickness", 350.0, unit="mm", min=200.0),
        number(
            "bottomCoverMm", "Bottom clear cover (cast against soil)", 75.0, unit="mm", min=40.0
        ),
        number("barDiaMm", "Default footing bar diameter", 16.0, unit="mm", min=10.0, max=32.0),
    ],
    requires_project=False,
)
def footing_defaults(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate default pad footing geometry, effective depth, and cover against active pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ft = safe_table(pack, "foundations")
        sh = getattr(ft, "shallow", None) if ft else None
        pack_cover = float(getattr(sh, "soilCover", 75.0) or 75.0)
    d_eff = values["minThicknessMm"] - values["bottomCoverMm"] - 1.5 * values["barDiaMm"]
    return result(
        summary={
            "minThicknessMm": values["minThicknessMm"],
            "effectiveDepthMm": d_eff,
            "packSoilCoverMm": pack_cover,
        },
        tables=[
            table(
                "Footing geometry defaults",
                [("parameter", "Parameter"), ("value", "Value", "mm")],
                [
                    {"parameter": "Minimum thickness", "value": values["minThicknessMm"]},
                    {"parameter": "Bottom cover", "value": values["bottomCoverMm"]},
                    {"parameter": "Average effective depth d", "value": d_eff},
                    {"parameter": "Code pack soil cover", "value": pack_cover},
                ],
            )
        ],
        notes=["Effective depth accounts for two orthogonal bar layers."],
    )


@feature(
    "settingsFoundation.pileDefaults",
    "Pile Defaults",
    part="settings",
    fields=[
        number("diameterMm", "Default pile diameter", 600.0, unit="mm", min=250.0),
        number("spacingRatio", "Minimum center-to-center spacing (× D)", 3.0, min=2.0, max=6.0),
        number("edgeOffsetRatio", "Pile cap edge distance (× D)", 1.5, min=1.0, max=3.0),
    ],
    requires_project=False,
)
def pile_defaults(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check default pile diameter, spacing, and pile cap overhang against active pack rules."""
    st = load_settings(ctx)
    d_mm = values["diameterMm"]
    sp_mm = d_mm * values["spacingRatio"]
    edge_mm = d_mm * values["edgeOffsetRatio"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ft = safe_table(pack, "foundations")
        controls = getattr(ft, "pileControls", None) if ft else None
    return result(
        summary={
            "diameterMm": d_mm,
            "minSpacingMm": sp_mm,
            "minEdgeMm": edge_mm,
            "hasPackControls": controls is not None,
        },
        tables=[
            table(
                "Pile layout defaults",
                [("parameter", "Parameter"), ("value", "Value", "mm")],
                [
                    {"parameter": "Pile diameter D", "value": d_mm},
                    {"parameter": "Min spacing", "value": sp_mm},
                    {"parameter": "Min cap edge distance", "value": edge_mm},
                ],
            )
        ],
        notes=["Standard minimum spacing 2.5D-3.0D avoids group installation interference."],
    )


@feature(
    "settingsFoundation.raftDefaults",
    "Raft Defaults",
    part="settings",
    fields=[
        number("raftThicknessMm", "Default raft slab thickness", 750.0, unit="mm", min=300.0),
        number("columnSpanM", "Typical column grid spacing", 6.5, unit="m", min=2.0),
        number("meshBarMm", "Default top/bottom mesh bar", 16.0, unit="mm", min=10.0),
        number("meshSpacingMm", "Default mesh spacing", 150.0, unit="mm", min=75.0),
    ],
    requires_project=False,
)
def raft_defaults(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate default raft thickness-to-span ratio and reinforcement steel area per metre."""
    t_mm = values["raftThicknessMm"]
    span_mm = values["columnSpanM"] * 1000.0
    as_per_m = (math.pi * values["meshBarMm"] ** 2 / 4.0) * (1000.0 / values["meshSpacingMm"])
    rho_face = as_per_m / (1000.0 * t_mm)
    return result(
        summary={
            "raftThicknessMm": t_mm,
            "spanToThickness": span_mm / t_mm,
            "faceSteelMm2PerM": as_per_m,
            "faceRatio": rho_face,
        },
        tables=[
            table(
                "Raft foundation defaults",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Span / thickness", "value": span_mm / t_mm},
                    {"metric": "Mesh steel per face [mm²/m]", "value": as_per_m},
                    {"metric": "Steel ratio per face", "value": rho_face},
                ],
            )
        ],
        notes=[
            "Two-way mat slabs typically require 0.18% minimum temperature/shrinkage steel per face."
        ],
    )


@feature(
    "settingsFoundation.coverSpacing",
    "Cover & Spacing",
    part="settings",
    fields=[
        number("soilCoverMm", "Cast-against-earth cover", 75.0, unit="mm", min=40.0),
        number("formedCoverMm", "Formed earth-face cover", 50.0, unit="mm", min=25.0),
        number("minClearMm", "Minimum clear bar spacing", 100.0, unit="mm", min=50.0),
        number("maxClearMm", "Maximum clear bar spacing", 300.0, unit="mm", min=150.0),
    ],
    requires_project=False,
)
def cover_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify nominal foundation concrete covers and bar spacing bounds against active pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        conc = safe_table(pack, "concrete")
        min_slab_sp = float(getattr(conc, "minSlabSpacing", 100.0) or 100.0)
    valid_sp = values["minClearMm"] >= min_slab_sp and values["maxClearMm"] >= values["minClearMm"]
    rows = [
        {"rule": "Cast against earth cover", "mm": values["soilCoverMm"]},
        {"rule": "Formed / blinded face cover", "mm": values["formedCoverMm"]},
        {"rule": "Min bar spacing", "mm": values["minClearMm"]},
        {"rule": "Max bar spacing", "mm": values["maxClearMm"]},
    ]
    return result(
        summary={
            "soilCoverMm": values["soilCoverMm"],
            "formedCoverMm": values["formedCoverMm"],
            "packMinSpacingMm": min_slab_sp,
            "valid": valid_sp,
        },
        tables=[
            table(
                "Foundation cover & spacing rules", [("rule", "Rule"), ("mm", "Value", "mm")], rows
            )
        ],
        notes=[
            "Validates foundation bar spacing bounds against active code pack minimum slab spacing."
        ],
    )


@feature(
    "settingsFoundation.barDiameters",
    "Bar Diameters",
    part="settings",
    fields=[],
    requires_project=False,
)
def bar_diameters(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List permitted foundation, main, and stirrup bar diameters from the active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        from saengine.design import bars

        fnd_bars = bars.diameters("foundation")
        main_bars = bars.diameters("main")
        st_bars = bars.diameters("stirrup")
    rows = [
        {
            "group": "Foundation mesh & footings",
            "diametersMm": ", ".join(f"{d:g}" for d in fnd_bars),
            "count": len(fnd_bars),
        },
        {
            "group": "Main frame bars",
            "diametersMm": ", ".join(f"{d:g}" for d in main_bars),
            "count": len(main_bars),
        },
        {
            "group": "Stirrups & ties",
            "diametersMm": ", ".join(f"{d:g}" for d in st_bars),
            "count": len(st_bars),
        },
    ]
    return result(
        summary={
            "foundationBarCount": len(fnd_bars),
            "minFoundationBarMm": min(fnd_bars),
            "maxFoundationBarMm": max(fnd_bars),
        },
        tables=[
            table(
                "Code pack bar diameter sets",
                [("group", "Group"), ("diametersMm", "Diameters [mm]"), ("count", "Count")],
                rows,
            )
        ],
        notes=["Bar sets retrieved from active code pack concrete.barDiameters."],
    )


@feature(
    "settingsFoundation.anchorageRules",
    "Anchorage Rules",
    part="settings",
    fields=[
        number("barDiameterMm", "Foundation bar diameter db", 16.0, unit="mm", min=10.0, max=32.0),
        number("fcMpa", "Concrete strength f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar yield fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def anchorage_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute straight tension development length and 90° hook anchorage in foundation concrete."""
    db = values["barDiameterMm"]
    fc = values["fcMpa"]
    fy = values["fyMpa"]
    # Standard bond-based tension development & 90-deg hook anchorage
    ld_straight = max(300.0, (fy / (1.1 * math.sqrt(min(fc, 69.0)))) * db * 0.5)
    ld_hook = max(150.0, 8.0 * db, (0.24 * fy / math.sqrt(min(fc, 69.0))) * db)
    rows = [
        {
            "anchorage": "Straight tension development ld",
            "lengthMm": ld_straight,
            "multipleDb": ld_straight / db,
        },
        {
            "anchorage": "Standard 90° hook development ldh",
            "lengthMm": ld_hook,
            "multipleDb": ld_hook / db,
        },
    ]
    return result(
        summary={"straightDevelopmentMm": ld_straight, "hookDevelopmentMm": ld_hook},
        tables=[
            table(
                "Foundation bar anchorage",
                [("anchorage", "Type"), ("lengthMm", "Length", "mm"), ("multipleDb", "× db")],
                rows,
            )
        ],
        notes=[
            "Check available footing projection (L - c1)/2 - cover against required ld or use hooks."
        ],
    )


@feature(
    "settingsFoundation.subgradeModel",
    "Subgrade Model",
    part="settings",
    fields=[
        select(
            "modelType",
            "Subgrade interaction model",
            [
                ("winkler", "Winkler uncoupled springs"),
                ("pseudoCoupled", "Pseudo-coupled (edge stiffened)"),
                ("continuum", "Elastic continuum half-space"),
            ],
            "pseudoCoupled",
        ),
        number(
            "centerKsKnPerM3", "Interior subgrade modulus ks", 25000.0, unit="kN/m³", min=1000.0
        ),
    ],
    requires_project=False,
)
def subgrade_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure soil-structure subgrade spring distribution (uniform vs edge-stiffened)."""
    ks = values["centerKsKnPerM3"]
    edge_mult = 2.0 if values["modelType"] == "pseudoCoupled" else 1.0
    rows = [
        {"zone": "Interior raft area", "ksKnPerM3": ks},
        {"zone": "Perimeter edge strip (1-2 m)", "ksKnPerM3": ks * edge_mult},
    ]
    return result(
        summary={
            "modelType": values["modelType"],
            "interiorKsKnPerM3": ks,
            "edgeKsKnPerM3": ks * edge_mult,
        },
        tables=[
            table(
                "Subgrade spring zoning",
                [("zone", "Zone"), ("ksKnPerM3", "Modulus ks", "kN/m³")],
                rows,
            )
        ],
        notes=[
            "Pseudo-coupled edge stiffening reflects higher contact pressure under rigid edges in elastic continua."
        ],
    )


@feature(
    "settingsFoundation.interfaceElements",
    "Interface Elements",
    part="settings",
    fields=[
        number("soilPhiDeg", "Soil friction angle φ'", 30.0, unit="°", min=10.0, max=45.0),
        number("interfaceFactor", "Wall/base friction ratio δ/φ'", 0.67, min=0.3, max=1.0),
        number("normalPressureKpa", "Interface normal stress σn", 120.0, unit="kPa", min=1.0),
    ],
    requires_project=False,
)
def interface_elements(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate soil-concrete interface friction angle and shear slip capacity."""
    delta = values["soilPhiDeg"] * values["interfaceFactor"]
    mu = math.tan(math.radians(delta))
    tau_max = values["normalPressureKpa"] * mu
    return result(
        summary={"interfaceFrictionDeg": delta, "frictionCoeff": mu, "shearCapacityKpa": tau_max},
        tables=[
            table(
                "Soil-structure interface parameters",
                [("parameter", "Parameter"), ("value", "Value")],
                [
                    {"parameter": "Interface δ [°]", "value": delta},
                    {"parameter": "Friction coeff tan δ", "value": mu},
                    {"parameter": "Limiting shear τmax [kPa]", "value": tau_max},
                ],
            )
        ],
        notes=["No-tension interface elements release uplift while limiting shear to σn·tan δ."],
    )


@feature(
    "settingsFoundation.nonlinearSprings",
    "Nonlinear Springs",
    part="settings",
    fields=[
        number("ksKnPerM3", "Initial elastic subgrade ks", 20000.0, unit="kN/m³", min=500.0),
        number("qultKpa", "Ultimate bearing capacity qult", 400.0, unit="kPa", min=20.0),
        number(
            "tensionCutoffKpa", "Tension capacity (0 = compression-only)", 0.0, unit="kPa", min=0.0
        ),
    ],
    requires_project=False,
)
def nonlinear_springs(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build bilinear elastic-perfectly-plastic compression-only soil spring curve."""
    ks = values["ksKnPerM3"]
    qult = values["qultKpa"]
    dy_mm = (qult / ks) * 1000.0
    rows = [
        {"settlementMm": -5.0, "pressureKpa": -values["tensionCutoffKpa"]},
        {"settlementMm": 0.0, "pressureKpa": 0.0},
        {"settlementMm": dy_mm, "pressureKpa": qult},
        {"settlementMm": dy_mm * 3.0, "pressureKpa": qult},
    ]
    return result(
        summary={
            "yieldSettlementMm": dy_mm,
            "ultimateCapacityKpa": qult,
            "compressionOnly": values["tensionCutoffKpa"] == 0.0,
        },
        tables=[
            table(
                "Bilinear soil spring backbone",
                [("settlementMm", "Displacement", "mm"), ("pressureKpa", "Pressure", "kPa")],
                rows,
            )
        ],
        notes=["Compression-only springs yield at δy = qult / ks and carry zero tension."],
    )


@feature(
    "settingsFoundation.consolidationSettings",
    "Consolidation Settings",
    part="settings",
    fields=[
        number("clayThicknessM", "Compressible clay layer thickness H", 6.0, unit="m", min=0.5),
        number("cvM2PerYear", "Coefficient of consolidation cv", 2.5, unit="m²/yr", min=0.05),
        select(
            "drainage",
            "Drainage boundary condition",
            [("double", "Double drainage (top & bottom)"), ("single", "Single drainage (one-way)")],
            "double",
        ),
        number(
            "targetDegreePct", "Target consolidation degree U", 90.0, unit="%", min=10.0, max=99.0
        ),
    ],
    requires_project=False,
)
def consolidation_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Terzaghi 1D consolidation drainage path and time to target degree U."""
    hdr = (
        values["clayThicknessM"] / 2.0
        if values["drainage"] == "double"
        else values["clayThicknessM"]
    )
    u = values["targetDegreePct"] / 100.0
    tv = (math.pi / 4.0) * u**2 if u < 0.6 else (-0.9332 * math.log10(1.0 - u) - 0.0851)
    t_years = tv * (hdr**2) / values["cvM2PerYear"]
    return result(
        summary={"drainagePathM": hdr, "timeFactorTv": tv, "timeYears": t_years},
        tables=[
            table(
                "1D consolidation time estimate",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Drainage path Hdr [m]", "value": hdr},
                    {"metric": "Time factor Tv", "value": tv},
                    {"metric": f"Time to {u * 100:.0f}% consolidation [yr]", "value": t_years},
                ],
            )
        ],
        notes=["Terzaghi 1D consolidation: t = Tv Hdr² / cv."],
    )


@feature(
    "settingsFoundation.contactStiffness",
    "Contact Stiffness",
    part="settings",
    fields=[
        number("soilModulusMpa", "Soil drained modulus Es", 25.0, unit="MPa", min=1.0),
        number("poisson", "Soil Poisson ratio ν", 0.30, min=0.1, max=0.49),
        number("elementSizeM", "Contact element size L", 1.0, unit="m", min=0.1),
    ],
    requires_project=False,
)
def contact_stiffness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive normal and tangential interface penalty stiffnesses from soil elastic constants."""
    es_kpa = values["soilModulusMpa"] * 1000.0
    nu = values["poisson"]
    g_kpa = es_kpa / (2.0 * (1.0 + nu))
    kn = es_kpa / values["elementSizeM"]
    kt = g_kpa / values["elementSizeM"]
    return result(
        summary={
            "shearModulusKpa": g_kpa,
            "normalStiffnessKpaPerM": kn,
            "tangentialStiffnessKpaPerM": kt,
        },
        tables=[
            table(
                "Interface penalty stiffness",
                [("component", "Component"), ("stiffnessKpaPerM", "Stiffness", "kPa/m")],
                [
                    {"component": "Normal kn", "stiffnessKpaPerM": kn},
                    {"component": "Tangential kt", "stiffnessKpaPerM": kt},
                ],
            )
        ],
        notes=["Normal and shear contact stiffnesses scaled by characteristic element thickness."],
    )


@feature(
    "settingsFoundation.waterproofingSystem",
    "Waterproofing System",
    part="settings",
    fields=[
        number("hydrostaticHeadM", "Design hydrostatic water head", 3.5, unit="m", min=0.0),
        select(
            "system",
            "Membrane system",
            [
                ("bituminous", "Torch-applied SBS sheet (4 mm)"),
                ("hdpe", "Pre-applied HDPE blindside (1.5 mm)"),
                ("crystalline", "Integral crystalline + waterstop"),
            ],
            "hdpe",
        ),
    ],
    requires_project=False,
)
def waterproofing_system(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Specify buried substructure waterproofing system based on hydrostatic pressure head."""
    p_kpa = values["hydrostaticHeadM"] * 9.81
    rows = [
        {"item": "Design water head [m]", "spec": f"{values['hydrostaticHeadM']:.2f}"},
        {"item": "Hydrostatic pressure [kPa]", "spec": f"{p_kpa:.1f}"},
        {"item": "Selected membrane", "spec": values["system"]},
        {
            "item": "Joint protection",
            "spec": "Hydrophilic + PVC centerbulb waterstops"
            if p_kpa > 10.0
            else "Standard construction joint sealant",
        },
    ]
    return result(
        summary={
            "hydrostaticHeadM": values["hydrostaticHeadM"],
            "pressureKpa": p_kpa,
            "system": values["system"],
        },
        tables=[
            table(
                "Waterproofing specification", [("item", "Item"), ("spec", "Specification")], rows
            )
        ],
        notes=[
            "Positive hydrostatic heads require continuous blindside membrane and joint waterstops."
        ],
    )


@feature(
    "settingsFoundation.drainageLayer",
    "Drainage Layer",
    part="settings",
    fields=[
        number("wallHeightM", "Retaining wall drained height", 4.5, unit="m", min=1.0),
        number(
            "inflowLPerMinPerM", "Design seepage inflow per m wall", 1.2, unit="L/(min·m)", min=0.1
        ),
    ],
    requires_project=False,
)
def drainage_layer(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size geocomposite wall drainage board flow capacity and perforated collector pipe."""
    q_m3_s_m = values["inflowLPerMinPerM"] / 60000.0
    req_transmissivity = q_m3_s_m * 3.0  # factor of safety 3
    pipe_dia_mm = 100.0 if values["inflowLPerMinPerM"] < 2.0 else 150.0
    return result(
        summary={
            "inflowLPerMinM": values["inflowLPerMinPerM"],
            "requiredTransmissivityM2PerS": req_transmissivity,
            "collectorPipeMm": pipe_dia_mm,
        },
        tables=[
            table(
                "Subsurface drainage sizing",
                [("item", "Parameter"), ("value", "Value")],
                [
                    {"item": "Required transmissivity [m²/s]", "value": req_transmissivity},
                    {"item": "Collector pipe diameter [mm]", "value": pipe_dia_mm},
                ],
            )
        ],
        notes=["Geotextile filter fabric should wrap gravel/board to prevent fine soil migration."],
    )


@feature(
    "settingsFoundation.sumpAllowance",
    "Sump Allowance",
    part="settings",
    fields=[
        number("basementAreaM2", "Basement footprint area", 1000.0, unit="m²", min=20.0),
        number("seepageRateLPerM2Hr", "Estimated seepage rate", 0.25, unit="L/(m²·hr)", min=0.01),
        number("detentionMin", "Pump cycle buffer time", 30.0, unit="min", min=5.0),
    ],
    requires_project=False,
)
def sump_allowance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size basement dewatering sump pit volume and duplex pump flow rate."""
    q_l_hr = values["basementAreaM2"] * values["seepageRateLPerM2Hr"]
    q_l_s = q_l_hr / 3600.0
    pit_vol_m3 = max(0.5, (q_l_hr * (values["detentionMin"] / 60.0)) / 1000.0)
    return result(
        summary={
            "inflowLPerS": q_l_s,
            "sumpVolumeM3": pit_vol_m3,
            "pumpCapacityLPerS": q_l_s * 2.0,
        },
        tables=[
            table(
                "Basement sump sizing",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Design seepage [L/s]", "value": q_l_s},
                    {"metric": "Duty pump rate (2×) [L/s]", "value": q_l_s * 2.0},
                    {"metric": "Sump storage volume [m³]", "value": pit_vol_m3},
                ],
            )
        ],
        notes=["Duplex pumps with 2× inflow duty capacity provide standby redundancy."],
    )


@feature(
    "settingsFoundation.hydrostaticDesign",
    "Hydrostatic Design",
    part="settings",
    fields=[
        number("submergedDepthM", "Slab depth below design water level", 2.0, unit="m", min=0.0),
        number(
            "deadWeightKnPerM2",
            "Resisting permanent slab/ballast weight",
            18.0,
            unit="kN/m²",
            min=1.0,
        ),
    ],
    requires_project=False,
)
def hydrostatic_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check basement uplift buoyancy factor of safety against design groundwater level."""
    uplift = values["submergedDepthM"] * 9.81
    fs = values["deadWeightKnPerM2"] / uplift if uplift > 0 else 99.0
    return result(
        summary={
            "upliftPressureKpa": uplift,
            "resistingDeadKpa": values["deadWeightKnPerM2"],
            "flotationSafetyFactor": fs,
            "adequate": fs >= 1.15,
        },
        tables=[
            table(
                "Hydrostatic uplift check",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Uplift pressure [kPa]", "value": uplift},
                    {"item": "Resisting dead [kPa]", "value": values["deadWeightKnPerM2"]},
                    {"item": "Factor of safety", "value": fs},
                ],
            )
        ],
        notes=["Requires FS >= 1.15-1.20 against flotation or tension piles / anchors."],
    )


@feature(
    "settingsFoundation.dampProofing",
    "Damp Proofing",
    part="settings",
    fields=[
        number(
            "membraneThicknessMm", "Polyethylene DPM thickness", 0.30, unit="mm", min=0.15, max=2.0
        ),
        number(
            "sandBlindingMm",
            "Protective sand cushion thickness",
            50.0,
            unit="mm",
            min=0.0,
            max=150.0,
        ),
    ],
    requires_project=False,
)
def damp_proofing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Specify ground-floor slab damp-proof membrane and vapour retarder buildup."""
    return result(
        summary={
            "membraneThicknessMm": values["membraneThicknessMm"],
            "sandCushionMm": values["sandBlindingMm"],
        },
        tables=[
            table(
                "Ground slab DPM buildup",
                [("layer", "Layer"), ("thicknessMm", "Thickness", "mm")],
                [
                    {
                        "layer": "DPM polyethylene sheet",
                        "thicknessMm": values["membraneThicknessMm"],
                    },
                    {"layer": "Sand blinding cushion", "thicknessMm": values["sandBlindingMm"]},
                ],
            )
        ],
        notes=["Overlap DPM joints by at least 150 mm and tape seals continuously."],
    )


@feature(
    "settingsFoundation.excavationSupport",
    "Excavation Support",
    part="settings",
    fields=[
        number("excavationDepthM", "Planned excavation depth", 5.0, unit="m", min=0.5),
        select(
            "soilKind",
            "Predominant soil",
            [("clay", "Soft/medium clay"), ("sand", "Granular sand"), ("rock", "Competent rock")],
            "sand",
        ),
    ],
    requires_project=False,
)
def excavation_support(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recommend default temporary shoring system based on excavation depth and ground type."""
    d = values["excavationDepthM"]
    sk = values["soilKind"]
    if sk == "rock" and d <= 4.0:
        rec = "Benched rock cut / rock bolts"
    elif d <= 2.5:
        rec = "Open battered cut (or trench box)"
    elif d <= 6.0:
        rec = "Cantilevered sheet pile / soldier pile & lagging"
    else:
        rec = "Propped secant/diaphragm wall with multi-level struts or tiebacks"
    return result(
        summary={"depthM": d, "soilKind": sk, "recommendedSupport": rec},
        tables=[
            table(
                "Temporary excavation support recommendation",
                [("depthM", "Depth", "m"), ("soil", "Soil"), ("system", "Recommended system")],
                [{"depthM": d, "soil": sk, "system": rec}],
            )
        ],
        notes=[
            "Verify adjacent property surcharge and groundwater drawdown before selecting open cut."
        ],
    )


@feature(
    "settingsFoundation.backfillSpec",
    "Backfill Spec",
    part="settings",
    fields=[
        number(
            "maxLiftMm", "Maximum compacted lift thickness", 200.0, unit="mm", min=100.0, max=400.0
        ),
        number(
            "maxPlasticityIndex",
            "Maximum fines plasticity index PI",
            12.0,
            unit="%",
            min=0.0,
            max=30.0,
        ),
        number(
            "unitWeightKnM3", "Target compacted unit weight", 18.5, unit="kN/m³", min=15.0, max=22.0
        ),
    ],
    requires_project=False,
)
def backfill_spec(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define structural backfill material grading, lift thickness, and unit weight defaults."""
    st = load_settings(ctx)
    return result(
        summary={
            "maxLiftMm": values["maxLiftMm"],
            "maxPiPct": values["maxPlasticityIndex"],
            "settingsUnitWeightKnM3": st.foundation.soilUnitWeight,
        },
        tables=[
            table(
                "Structural backfill specification",
                [("parameter", "Parameter"), ("value", "Value")],
                [
                    {"parameter": "Max loose lift [mm]", "value": values["maxLiftMm"]},
                    {
                        "parameter": "Max plasticity index [%]",
                        "value": values["maxPlasticityIndex"],
                    },
                    {"parameter": "Target γ [kN/m³]", "value": values["unitWeightKnM3"]},
                ],
            )
        ],
        notes=[
            "Low-plasticity granular backfill minimizes lateral swelling pressure on basement walls."
        ],
    )


@feature(
    "settingsFoundation.compactionRequirement",
    "Compaction Requirement",
    part="settings",
    fields=[
        number(
            "proctorPct", "Minimum standard Proctor density", 95.0, unit="%", min=85.0, max=102.0
        ),
        number("maxDryDensityKgM3", "Lab max dry density", 1950.0, unit="kg/m³", min=1400.0),
    ],
    requires_project=False,
)
def compaction_requirement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate minimum field dry density target from Proctor compaction percentage."""
    target_dry = values["maxDryDensityKgM3"] * (values["proctorPct"] / 100.0)
    return result(
        summary={"proctorPct": values["proctorPct"], "targetDryDensityKgM3": target_dry},
        tables=[
            table(
                "Field compaction target",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Required Proctor [%]", "value": values["proctorPct"]},
                    {"metric": "Min field dry density [kg/m³]", "value": target_dry},
                ],
            )
        ],
        notes=["Verify field density every lift with nuclear gauge or sand-cone tests."],
    )


@feature(
    "settingsFoundation.blindingThickness",
    "Blinding Thickness",
    part="settings",
    fields=[
        number(
            "thicknessMm", "Lean concrete blinding thickness", 75.0, unit="mm", min=40.0, max=200.0
        ),
        number("footingAreaM2", "Total foundation footprint area", 250.0, unit="m²", min=1.0),
    ],
    requires_project=False,
)
def blinding_thickness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Specify lean concrete blinding thickness and estimate blinding concrete volume."""
    vol_m3 = values["footingAreaM2"] * (values["thicknessMm"] / 1000.0)
    return result(
        summary={"blindingMm": values["thicknessMm"], "volumeM3": vol_m3},
        tables=[
            table(
                "Blinding layer takeoff",
                [
                    ("areaM2", "Footprint", "m²"),
                    ("thicknessMm", "Thickness", "mm"),
                    ("volumeM3", "Volume", "m³"),
                ],
                [
                    {
                        "areaM2": values["footingAreaM2"],
                        "thicknessMm": values["thicknessMm"],
                        "volumeM3": vol_m3,
                    }
                ],
            )
        ],
        notes=["Lean concrete blinding protects subgrade and supports reinforcement chairs."],
    )


@feature(
    "settingsFoundation.workingSpace",
    "Working Space",
    part="settings",
    fields=[
        number(
            "formworkClearanceMm",
            "Clearance outside footing edge",
            600.0,
            unit="mm",
            min=200.0,
            max=1500.0,
        ),
        number("footingLengthM", "Footing length L", 2.4, unit="m", min=0.5),
        number("footingWidthM", "Footing width B", 2.4, unit="m", min=0.5),
    ],
    requires_project=False,
)
def working_space(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute pit excavation plan dimensions including perimeter formwork working space."""
    ws_m = values["formworkClearanceMm"] / 1000.0
    exc_l = values["footingLengthM"] + 2.0 * ws_m
    exc_b = values["footingWidthM"] + 2.0 * ws_m
    ratio = (exc_l * exc_b) / (values["footingLengthM"] * values["footingWidthM"])
    return result(
        summary={
            "excavationLengthM": exc_l,
            "excavationWidthM": exc_b,
            "areaExpansionFactor": ratio,
        },
        tables=[
            table(
                "Excavation working space",
                [
                    ("dim", "Dimension"),
                    ("footingM", "Footing", "m"),
                    ("excavationM", "Excavation", "m"),
                ],
                [
                    {"dim": "Length", "footingM": values["footingLengthM"], "excavationM": exc_l},
                    {"dim": "Width", "footingM": values["footingWidthM"], "excavationM": exc_b},
                ],
            )
        ],
        notes=["Accounts for perimeter formwork, waterproofing application, and drainage access."],
    )
