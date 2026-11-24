"""Project Settings - Units & Coordinates tab: unit systems, conversions, project coordinates, precision."""

from __future__ import annotations

import math
from typing import Any

from saengine import units as units_lib
from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.settings_common import load_settings


@feature(
    "settingsUnits.unitSystem",
    "Unit System",
    part="settings",
    fields=[
        select(
            "system",
            "Preview unit system",
            [("SI", "SI (mm, m, kN, MPa)"), ("USCustomary", "US Customary (in, ft, kip, ksi)")],
            "SI",
        ),
    ],
    requires_project=False,
)
def unit_system(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare stored SI base units with the selected display unit system across all quantities."""
    st = load_settings(ctx)
    u = units_lib.units_of({"system": values["system"]})
    rows = [
        {"id": k, "title": kind.title, "si": kind.si, "display": u.unit(k)}
        for k, kind in list(units_lib.KINDS.items())[:15]
    ]
    return result(
        summary={
            "projectSystem": st.units.system,
            "previewSystem": values["system"],
            "quantityCount": len(units_lib.KINDS),
        },
        tables=[
            table(
                "Unit system mapping",
                [
                    ("id", "Quantity"),
                    ("title", "Description"),
                    ("si", "Stored SI"),
                    ("display", "Displayed"),
                ],
                rows,
            )
        ],
        notes=[
            "SAEngine stores and solves strictly in SI; display units convert values at presentation."
        ],
    )


@feature(
    "settingsUnits.lengthForce",
    "Length & Force",
    part="settings",
    fields=[
        number("lengthM", "Sample length", 6.0, unit="m", min=0.0),
        number("forceKn", "Sample force", 250.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def length_force(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert length, force, and implied moment between SI and US customary units."""
    l_m = values["lengthM"]
    f_kn = values["forceKn"]
    m_knm = f_kn * l_m
    rows = [
        {
            "quantity": "Length",
            "si": f"{l_m:.3f} m",
            "us": f"{l_m / units_lib.FOOT:.3f} ft ({l_m / units_lib.INCH:.1f} in)",
        },
        {
            "quantity": "Force",
            "si": f"{f_kn:.2f} kN",
            "us": f"{f_kn * 1000.0 / units_lib.KIP:.2f} kip",
        },
        {
            "quantity": "Moment",
            "si": f"{m_knm:.2f} kN·m",
            "us": f"{m_knm * 1000.0 / (units_lib.KIP * units_lib.FOOT):.2f} kip·ft",
        },
    ]
    return result(
        summary={
            "lengthFt": l_m / units_lib.FOOT,
            "forceKip": f_kn * 1000.0 / units_lib.KIP,
            "momentKipFt": m_knm * 1000.0 / (units_lib.KIP * units_lib.FOOT),
        },
        tables=[
            table(
                "Length & force conversions",
                [("quantity", "Quantity"), ("si", "SI"), ("us", "US Customary")],
                rows,
            )
        ],
        notes=["Exact NIST SP 811 constants: 1 ft = 0.3048 m, 1 kip = 4.44822 kN."],
    )


@feature(
    "settingsUnits.stressUnits",
    "Stress Units",
    part="settings",
    fields=[
        number("stressMpa", "Stress / strength value", 30.0, unit="MPa", min=0.0),
    ],
    requires_project=False,
)
def stress_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert stress and modulus values between MPa, kPa, ksi, and psi."""
    mpa = values["stressMpa"]
    psi = mpa * 1e6 / (units_lib.POUND_FORCE / units_lib.INCH**2)
    ksi = psi / 1000.0
    return result(
        summary={"mpa": mpa, "kpa": mpa * 1000.0, "ksi": ksi, "psi": psi},
        tables=[
            table(
                "Stress unit equivalents",
                [("unit", "Unit"), ("value", "Value")],
                [
                    {"unit": "MPa (N/mm²)", "value": mpa},
                    {"unit": "kPa (kN/m²)", "value": mpa * 1000.0},
                    {"unit": "ksi", "value": ksi},
                    {"unit": "psi", "value": psi},
                ],
            )
        ],
        notes=["1 MPa = 1 N/mm² = 1000 kPa ≈ 0.145038 ksi."],
    )


@feature(
    "settingsUnits.numberFormat",
    "Number Format",
    part="settings",
    fields=[
        number("sampleNumber", "Sample number", 1234567.89),
        select(
            "separator",
            "Grouping & decimal style",
            [
                ("commaDot", "1,234,567.89"),
                ("spaceComma", "1 234 567,89"),
                ("dotComma", "1.234.567,89"),
            ],
            "commaDot",
        ),
    ],
    requires_project=False,
)
def number_format(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview thousand-separator and decimal-symbol number formatting."""
    s = f"{values['sampleNumber']:,.2f}"
    if values["separator"] == "spaceComma":
        s = s.replace(",", " ").replace(".", ",")
    elif values["separator"] == "dotComma":
        s = s.replace(",", "_").replace(".", ",").replace("_", ".")
    return result(
        summary={"style": values["separator"], "formatted": s},
        tables=[
            table(
                "Number format preview",
                [("style", "Style"), ("formatted", "Output")],
                [{"style": values["separator"], "formatted": s}],
            )
        ],
        notes=["Controls tabular report and schedule number display."],
    )


@feature(
    "settingsUnits.currency",
    "Currency",
    part="settings",
    fields=[
        text("currencyCode", "Project currency ISO code", "USD"),
        number("exchangeRate", "Rate relative to USD", 1.0, min=0.0001),
        number("sampleCostUsd", "Sample baseline cost", 100000.0, min=0.0),
    ],
    requires_project=False,
)
def currency(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure BOQ currency code and exchange conversion preview."""
    converted = values["sampleCostUsd"] * values["exchangeRate"]
    return result(
        summary={
            "currency": values["currencyCode"],
            "exchangeRate": values["exchangeRate"],
            "convertedAmount": converted,
        },
        tables=[
            table(
                "Currency conversion",
                [("currency", "Currency"), ("rate", "Rate"), ("amount", "Amount")],
                [
                    {"currency": "USD", "rate": 1.0, "amount": values["sampleCostUsd"]},
                    {
                        "currency": values["currencyCode"],
                        "rate": values["exchangeRate"],
                        "amount": converted,
                    },
                ],
            )
        ],
        notes=["Used for BOQ rate tables and cost summaries."],
    )


@feature(
    "settingsUnits.dateTime",
    "Date & Time",
    part="settings",
    fields=[
        select(
            "dateFormat",
            "Date format",
            [
                ("YYYY-MM-DD", "ISO (YYYY-MM-DD)"),
                ("DD/MM/YYYY", "DD/MM/YYYY"),
                ("MM/DD/YYYY", "MM/DD/YYYY"),
            ],
            "YYYY-MM-DD",
        ),
        text("timeZone", "Project time zone", "UTC+06:00"),
    ],
    requires_project=False,
)
def date_time(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure project date formatting and time zone for audit logs and title blocks."""
    ex = {"YYYY-MM-DD": "2026-11-23", "DD/MM/YYYY": "23/11/2026", "MM/DD/YYYY": "11/23/2026"}[
        values["dateFormat"]
    ]
    return result(
        summary={"dateFormat": values["dateFormat"], "timeZone": values["timeZone"], "example": ex},
        tables=[
            table(
                "Date & time convention",
                [("field", "Setting"), ("value", "Value")],
                [
                    {"field": "Format", "value": values["dateFormat"]},
                    {"field": "Example", "value": ex},
                    {"field": "Time zone", "value": values["timeZone"]},
                ],
            )
        ],
        notes=["Audit log timestamps remain stored in UTC ISO-8601 internally."],
    )


@feature(
    "settingsUnits.projectBasePoint",
    "Project Base Point",
    part="settings",
    fields=[
        number("eastM", "Base point Easting X", 0.0, unit="m"),
        number("northM", "Base point Northing Y", 0.0, unit="m"),
        number("elevM", "Datum elevation Z", 0.0, unit="m"),
    ],
    requires_project=False,
)
def project_base_point(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect and validate project local origin coordinates and datum elevation."""
    st = load_settings(ctx)
    return result(
        summary={
            "eastingM": values["eastM"],
            "northingM": values["northM"],
            "elevationM": values["elevM"],
            "crs": st.ifc.crs,
        },
        tables=[
            table(
                "Project base point",
                [("axis", "Coordinate"), ("m", "Value", "m")],
                [
                    {"axis": "Easting (X)", "m": values["eastM"]},
                    {"axis": "Northing (Y)", "m": values["northM"]},
                    {"axis": "Elevation (Z)", "m": values["elevM"]},
                ],
            )
        ],
        notes=[f"IFC georeferencing CRS configured as {st.ifc.crs}."],
    )


@feature(
    "settingsUnits.surveyPoint",
    "Survey Point",
    part="settings",
    fields=[
        number("surveyEastM", "Survey Easting", 542150.0, unit="m"),
        number("surveyNorthM", "Survey Northing", 2634200.0, unit="m"),
        number("localX", "Model local X", 12.0, unit="m"),
        number("localY", "Model local Y", 8.0, unit="m"),
    ],
    requires_project=False,
)
def survey_point(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Transform model local coordinates to real-world survey Easting/Northing."""
    e = values["surveyEastM"] + values["localX"]
    n = values["surveyNorthM"] + values["localY"]
    return result(
        summary={"surveyEastingM": e, "surveyNorthingM": n},
        tables=[
            table(
                "Survey coordinate transform",
                [("coord", "Coordinate"), ("valueM", "Value", "m")],
                [
                    {"coord": "Global Easting", "valueM": e},
                    {"coord": "Global Northing", "valueM": n},
                ],
            )
        ],
        notes=["Maps structural grid coordinates to GIS / IFC survey CRS."],
    )


@feature(
    "settingsUnits.trueNorth",
    "True North",
    part="settings",
    fields=[
        number("angleDeg", "True North clockwise from +Y", 22.5, unit="°", min=-180.0, max=180.0),
    ],
    requires_project=False,
)
def true_north(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute rotation matrix transforming model coordinates to True North orientation."""
    th = math.radians(values["angleDeg"])
    return result(
        summary={
            "trueNorthDeg": values["angleDeg"],
            "cosTheta": math.cos(th),
            "sinTheta": math.sin(th),
        },
        tables=[
            table(
                "True North rotation",
                [("term", "Term"), ("value", "Value")],
                [
                    {"term": "cos θ", "value": math.cos(th)},
                    {"term": "sin θ", "value": math.sin(th)},
                ],
            )
        ],
        notes=[
            "Used for directional wind rose alignment, solar studies, and IFC IfcSite TrueNorth."
        ],
    )


@feature(
    "settingsUnits.momentUnits",
    "Moment Units",
    part="settings",
    fields=[
        number("momentKnM", "Bending moment", 150.0, unit="kN·m"),
    ],
    requires_project=False,
)
def moment_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert bending moment and torque across kN·m, N·mm, kip·ft, and kip·in."""
    m = values["momentKnM"]
    kip_ft = m * 1000.0 / (units_lib.KIP * units_lib.FOOT)
    kip_in = m * 1000.0 / (units_lib.KIP * units_lib.INCH)
    return result(
        summary={"knM": m, "nMm": m * 1e6, "kipFt": kip_ft, "kipIn": kip_in},
        tables=[
            table(
                "Moment unit conversion",
                [("unit", "Unit"), ("value", "Value")],
                [
                    {"unit": "kN·m", "value": m},
                    {"unit": "N·mm", "value": m * 1e6},
                    {"unit": "kip·ft", "value": kip_ft},
                    {"unit": "kip·in", "value": kip_in},
                ],
            )
        ],
        notes=["Exact conversion via NIST SP 811 kip and foot factors."],
    )


@feature(
    "settingsUnits.pressureUnits",
    "Pressure Units",
    part="settings",
    fields=[
        number("pressureKpa", "Area load / soil pressure", 5.0, unit="kN/m²"),
    ],
    requires_project=False,
)
def pressure_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert distributed pressure across kN/m² (kPa), MPa, psf, and ksf."""
    kpa = values["pressureKpa"]
    psf = kpa * 1000.0 / (units_lib.POUND_FORCE / units_lib.FOOT**2)
    ksf = psf / 1000.0
    return result(
        summary={"kpa": kpa, "mpa": kpa / 1000.0, "psf": psf, "ksf": ksf},
        tables=[
            table(
                "Pressure unit conversion",
                [("unit", "Unit"), ("value", "Value")],
                [
                    {"unit": "kN/m² (kPa)", "value": kpa},
                    {"unit": "MPa", "value": kpa / 1000.0},
                    {"unit": "psf", "value": psf},
                    {"unit": "ksf", "value": ksf},
                ],
            )
        ],
        notes=["1 kN/m² = 1 kPa ≈ 20.8854 psf."],
    )


@feature(
    "settingsUnits.temperatureUnits",
    "Temperature Units",
    part="settings",
    fields=[
        number("tempC", "Absolute temperature", 25.0, unit="°C"),
        number("deltaTC", "Temperature change ΔT", 20.0, unit="Δ°C"),
    ],
    requires_project=False,
)
def temperature_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert absolute temperature (°C/°F/K) and temperature change (Δ°C/Δ°F)."""
    tc = values["tempC"]
    dtc = values["deltaTC"]
    tf = tc * 1.8 + 32.0
    dtf = dtc * 1.8
    return result(
        summary={"tempC": tc, "tempF": tf, "tempK": tc + 273.15, "deltaTC": dtc, "deltaTF": dtf},
        tables=[
            table(
                "Temperature conversion",
                [("kind", "Quantity"), ("si", "SI"), ("us", "US")],
                [
                    {"kind": "Absolute temperature", "si": f"{tc:.2f} °C", "us": f"{tf:.2f} °F"},
                    {
                        "kind": "Temperature change ΔT",
                        "si": f"{dtc:.2f} Δ°C",
                        "us": f"{dtf:.2f} Δ°F",
                    },
                ],
            )
        ],
        notes=[
            "Absolute temperatures include the +32 °F offset; temperature changes scale by 1.8 only."
        ],
    )


@feature(
    "settingsUnits.densityUnits",
    "Density Units",
    part="settings",
    fields=[
        number("densityKgM3", "Mass density ρ", 2400.0, unit="kg/m³", min=1.0),
    ],
    requires_project=False,
)
def density_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert mass density and unit weight across kg/m³, kN/m³, and pcf."""
    rho = values["densityKgM3"]
    uw_knm3 = rho * 9.80665e-3
    pcf = rho * units_lib.FOOT**3 / units_lib.POUND
    return result(
        summary={"kgPerM3": rho, "knPerM3": uw_knm3, "pcf": pcf},
        tables=[
            table(
                "Density & unit weight",
                [("unit", "Unit"), ("value", "Value")],
                [
                    {"unit": "kg/m³", "value": rho},
                    {"unit": "kN/m³", "value": uw_knm3},
                    {"unit": "lb/ft³ (pcf)", "value": pcf},
                ],
            )
        ],
        notes=["Unit weight γ = ρ × 9.80665 m/s²."],
    )


@feature(
    "settingsUnits.energyUnits",
    "Energy Units",
    part="settings",
    fields=[
        number("energyMj", "Embodied energy", 500.0, unit="MJ", min=0.0),
    ],
    requires_project=False,
)
def energy_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert energy values across MJ, kWh, and BTU for embodied carbon & energy reports."""
    mj = values["energyMj"]
    kwh = mj / 3.6
    btu = mj * 947.81712
    return result(
        summary={"mj": mj, "kwh": kwh, "btu": btu},
        tables=[
            table(
                "Energy unit conversion",
                [("unit", "Unit"), ("value", "Value")],
                [
                    {"unit": "MJ", "value": mj},
                    {"unit": "kWh", "value": kwh},
                    {"unit": "BTU", "value": btu},
                ],
            )
        ],
        notes=["1 kWh = 3.6 MJ."],
    )


@feature(
    "settingsUnits.drawingScaleUnits",
    "Drawing Scale Units",
    part="settings",
    fields=[
        number("modelLengthMm", "Model length", 10000.0, unit="mm", min=1.0),
    ],
    requires_project=False,
)
def drawing_scale_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check model DXF unit ($INSUNITS=4 mm) scaling on plotted sheets."""
    st = load_settings(ctx)
    plotted_mm = values["modelLengthMm"] / st.drawings.planScale
    return result(
        summary={
            "dxfUnits": "mm ($INSUNITS=4)",
            "planScale": st.drawings.planScale,
            "plottedMm": plotted_mm,
        },
        tables=[
            table(
                "Drawing model-to-paper scaling",
                [("scale", "Scale"), ("modelMm", "Model", "mm"), ("paperMm", "Paper", "mm")],
                [
                    {
                        "scale": f"1:{st.drawings.planScale}",
                        "modelMm": values["modelLengthMm"],
                        "paperMm": plotted_mm,
                    }
                ],
            )
        ],
        notes=["CAD drafting DXF files use metric millimetres ($INSUNITS = 4)."],
    )


@feature(
    "settingsUnits.dimensionUnits",
    "Dimension Units",
    part="settings",
    fields=[
        number("dimensionMm", "Sample structural dimension", 450.0, unit="mm", min=1.0),
    ],
    requires_project=False,
)
def dimension_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Format structural dimension strings in mm, cm, m, or fractional inches."""
    mm = values["dimensionMm"]
    inches = (mm / 1000.0) / units_lib.INCH
    return result(
        summary={"mm": mm, "m": mm / 1000.0, "inches": inches},
        tables=[
            table(
                "Dimension display formats",
                [("unit", "Unit"), ("formatted", "Display")],
                [
                    {"unit": "mm", "formatted": f"{mm:.0f} mm"},
                    {"unit": "m", "formatted": f"{mm / 1000:.3f} m"},
                    {"unit": "in", "formatted": f"{inches:.2f} in"},
                ],
            )
        ],
        notes=["Member section dimensions default to mm in SI and in in US Customary."],
    )


@feature(
    "settingsUnits.elevationUnits",
    "Elevation Units",
    part="settings",
    fields=[
        number("elevationM", "Storey datum elevation", 10.55, unit="m"),
    ],
    requires_project=False,
)
def elevation_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Format structural level and foundation datum elevations in m, mm, or ft."""
    el = values["elevationM"]
    ft = el / units_lib.FOOT
    return result(
        summary={"elevationM": el, "elevationMm": el * 1000.0, "elevationFt": ft},
        tables=[
            table(
                "Elevation datum formats",
                [("unit", "Unit"), ("formatted", "Label")],
                [
                    {"unit": "m", "formatted": f"{el:+.3f} m"},
                    {"unit": "mm", "formatted": f"{el * 1000:+.0f} mm"},
                    {"unit": "ft", "formatted": f"{ft:+.2f} ft"},
                ],
            )
        ],
        notes=["Level tags include explicit + / - datum sign."],
    )


@feature(
    "settingsUnits.areaUnits",
    "Area Units",
    part="settings",
    fields=[
        number("areaM2", "Floor or plan area", 450.0, unit="m²", min=0.0),
    ],
    requires_project=False,
)
def area_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert plan and formwork areas across m², mm², and ft²."""
    m2 = values["areaM2"]
    ft2 = m2 / (units_lib.FOOT**2)
    return result(
        summary={"m2": m2, "ft2": ft2, "mm2": m2 * 1e6},
        tables=[
            table(
                "Area unit conversion",
                [("unit", "Unit"), ("value", "Value")],
                [
                    {"unit": "m²", "value": m2},
                    {"unit": "ft²", "value": ft2},
                    {"unit": "mm²", "value": m2 * 1e6},
                ],
            )
        ],
        notes=["1 m² ≈ 10.7639 ft²."],
    )


@feature(
    "settingsUnits.volumeUnits",
    "Volume Units",
    part="settings",
    fields=[
        number("volumeM3", "Concrete volume", 85.0, unit="m³", min=0.0),
    ],
    requires_project=False,
)
def volume_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert concrete and excavation volumes across m³, ft³, and yd³."""
    m3 = values["volumeM3"]
    ft3 = m3 / (units_lib.FOOT**3)
    yd3 = ft3 / 27.0
    return result(
        summary={"m3": m3, "ft3": ft3, "yd3": yd3},
        tables=[
            table(
                "Volume unit conversion",
                [("unit", "Unit"), ("value", "Value")],
                [
                    {"unit": "m³", "value": m3},
                    {"unit": "ft³", "value": ft3},
                    {"unit": "yd³", "value": yd3},
                ],
            )
        ],
        notes=["1 m³ ≈ 1.30795 yd³."],
    )


@feature(
    "settingsUnits.unitConversionTable",
    "Unit Conversion Table",
    part="settings",
    fields=[],
    requires_project=False,
)
def unit_conversion_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display the complete SI-to-US conversion table registered in saengine.units."""
    rows = []
    for k, kind in units_lib.KINDS.items():
        for us_label, factor in kind.us:
            rows.append({"kind": k, "si": kind.si, "us": us_label, "factor": factor})
    return result(
        summary={"conversionPairCount": len(rows), "kindCount": len(units_lib.KINDS)},
        tables=[
            table(
                "SAEngine unit conversion factors",
                [
                    ("kind", "Quantity"),
                    ("si", "SI unit"),
                    ("us", "US unit"),
                    ("factor", "SI × factor = US"),
                ],
                rows,
            )
        ],
        notes=["Generated directly from saengine.units.KINDS."],
    )


@feature(
    "settingsUnits.mixedUnitWarning",
    "Mixed Unit Warning",
    part="settings",
    fields=[],
    requires_project=False,
)
def mixed_unit_warning(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check whether project code pack suggested units align with display units."""
    st = load_settings(ctx)
    from saengine.features.settings_common import active_pack

    pack = active_pack(ctx, st)
    pack_units = getattr(pack.info, "units", None) or "SI"
    mismatch = pack_units != st.units.system
    return result(
        summary={
            "packUnits": pack_units,
            "projectDisplayUnits": st.units.system,
            "mixedUnitWarning": mismatch,
        },
        tables=[
            table(
                "Unit consistency check",
                [("source", "Source"), ("system", "Unit system")],
                [
                    {"source": f"Code pack ({pack.id})", "system": pack_units},
                    {"source": "Project display setting", "system": st.units.system},
                ],
            )
        ],
        notes=["Internal storage is always SI regardless of display unit system mismatch."],
    )


@feature(
    "settingsUnits.roundingOnConvert",
    "Rounding On Convert",
    part="settings",
    fields=[
        number("siValue", "Stored SI value", 300.0, min=0.0),
        number("decimals", "Target display decimals", 2.0, min=0.0, max=6.0),
    ],
    requires_project=False,
)
def rounding_on_convert(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check round-trip precision loss when converting SI -> US -> SI with display rounding."""
    si = values["siValue"]
    dec = int(values["decimals"])
    inches = round(si * 1e-3 / units_lib.INCH, dec)
    back_mm = inches * units_lib.INCH * 1000.0
    err = abs(back_mm - si)
    return result(
        summary={
            "siOriginalMm": si,
            "displayInches": inches,
            "roundTripMm": back_mm,
            "roundTripErrorMm": err,
        },
        tables=[
            table(
                "Round-trip conversion accuracy",
                [("step", "Step"), ("value", "Value")],
                [
                    {"step": "Original [mm]", "value": si},
                    {"step": "Rounded [in]", "value": inches},
                    {"step": "Round-trip [mm]", "value": back_mm},
                    {"step": "Error [mm]", "value": err},
                ],
            )
        ],
        notes=["Demonstrates why stored model geometry must remain unrounded SI."],
    )


@feature(
    "settingsUnits.importUnitMapping",
    "Import Unit Mapping",
    part="settings",
    fields=[
        select(
            "incomingUnit",
            "Incoming CAD/data length unit",
            [
                ("mm", "Millimetres (mm)"),
                ("m", "Metres (m)"),
                ("cm", "Centimetres (cm)"),
                ("in", "Inches (in)"),
                ("ft", "Feet (ft)"),
            ],
            "m",
        ),
        number("sampleCoord", "Sample incoming coordinate", 12.5),
    ],
    requires_project=False,
)
def import_unit_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute scale factor converting imported CAD/CSV coordinates into SAEngine internal mm."""
    factors_to_mm = {
        "mm": 1.0,
        "cm": 10.0,
        "m": 1000.0,
        "in": units_lib.INCH * 1000.0,
        "ft": units_lib.FOOT * 1000.0,
    }
    f = factors_to_mm[values["incomingUnit"]]
    converted_mm = values["sampleCoord"] * f
    return result(
        summary={
            "incomingUnit": values["incomingUnit"],
            "scaleToMm": f,
            "convertedMm": converted_mm,
        },
        tables=[
            table(
                "Import unit scaling",
                [
                    ("incoming", "Incoming"),
                    ("scaleToMm", "Multiplier to mm"),
                    ("convertedMm", "Result", "mm"),
                ],
                [
                    {
                        "incoming": f"{values['sampleCoord']} {values['incomingUnit']}",
                        "scaleToMm": f,
                        "convertedMm": converted_mm,
                    }
                ],
            )
        ],
        notes=["Maps external DXF/IFC/spreadsheet length units into internal model millimetres."],
    )


@feature(
    "settingsUnits.unitAuditTrail",
    "Unit Audit Trail",
    part="settings",
    fields=[],
    requires_project=False,
)
def unit_audit_trail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit active project unit configuration and per-quantity overrides."""
    st = load_settings(ctx)
    u_dict = st.units.model_dump(mode="json", exclude_none=True)
    rows = [{"field": k, "value": str(v)} for k, v in u_dict.items()]
    return result(
        summary={
            "system": st.units.system,
            "configuredFields": len(rows),
            "isDefaultSI": st.units.is_default(),
        },
        tables=[
            table(
                "Active unit configuration record", [("field", "Setting"), ("value", "Value")], rows
            )
        ],
        notes=["Stored in 02 Project Settings/project-settings.json under 'units'."],
    )
