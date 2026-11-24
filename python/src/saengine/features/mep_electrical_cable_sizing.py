"""Electrical cable derating and containment checks."""

from __future__ import annotations

import math

from saengine.features import feature, number, result, select


@feature(
    "mepElectricalCableSizing.groupingFactor",
    "Grouping Factor",
    part="mep",
    fields=[
        number("cableCount", "Grouped loaded cables", 8, min=1),
        number("baseAmpacityA", "Reference cable ampacity", 40, unit="A", min=0.1),
        number("groupFactor", "Grouping correction factor", 0.7, min=0.01, max=1),
    ],
    requires_project=False,
)
def grouping_factor(ctx, values: dict) -> dict:
    """Derate cable ampacity by the entered grouping correction factor."""
    corrected = values["baseAmpacityA"] * values["groupFactor"]
    return result(
        summary={"correctedAmpacityA": corrected, "groupedCables": int(values["cableCount"])},
        notes=[
            "Grouping correction is a project or installation-table input and is applied to reference ampacity."
        ],
    )


@feature(
    "mepElectricalCableSizing.ambientFactor",
    "Ambient Factor",
    part="mep",
    fields=[
        number("conductorLimitC", "Conductor temperature limit", 90, unit="°C", min=1),
        number("ambientC", "Route ambient temperature", 40, unit="°C", min=-40),
        number("referenceAmbientC", "Reference ambient temperature", 30, unit="°C", min=-40),
    ],
    requires_project=False,
)
def ambient_factor(ctx, values: dict) -> dict:
    """Calculate thermal derating using conductor-to-ambient temperature rise."""
    headroom = values["conductorLimitC"] - values["ambientC"]
    reference = values["conductorLimitC"] - values["referenceAmbientC"]
    if headroom <= 0 or reference <= 0:
        raise ValueError("Ambient and reference temperatures must be below the conductor limit.")
    factor = math.sqrt(headroom / reference)
    return result(
        summary={"ambientCorrectionFactor": factor},
        notes=[
            "Square-root temperature-rise correction; use cable-manufacturer data and applicable installation conditions for final selection."
        ],
    )


@feature(
    "mepElectricalCableSizing.thermalInsulation",
    "Thermal Insulation",
    part="mep",
    fields=[
        number("baseAmpacityA", "Uninsulated reference ampacity", 32, unit="A", min=0.1),
        number("insulationDeratingFactor", "Thermal insulation factor", 0.75, min=0.01, max=1),
        number("insulatedLengthM", "Cable length surrounded by insulation", 1, unit="m", min=0),
        number("totalLengthM", "Total cable length", 25, unit="m", min=0.1),
    ],
    requires_project=False,
)
def thermal_insulation(ctx, values: dict) -> dict:
    """Derate cable ampacity for thermal insulation around a route segment."""
    factor = values["insulationDeratingFactor"]
    return result(
        summary={
            "deratedAmpacityA": values["baseAmpacityA"] * factor,
            "insulatedLengthFraction": min(values["insulatedLengthM"] / values["totalLengthM"], 1),
        },
        notes=[
            "The entered factor represents the cable installation in its insulated section; ampacity must be checked for the most thermally restrictive segment."
        ],
    )


@feature(
    "mepElectricalCableSizing.soilConditions",
    "Soil Conditions",
    part="mep",
    fields=[
        number(
            "referenceResistivityKmW",
            "Reference soil thermal resistivity",
            2.5,
            unit="K·m/W",
            min=0.1,
        ),
        number("siteResistivityKmW", "Site soil thermal resistivity", 1.5, unit="K·m/W", min=0.1),
        number("referenceAmpacityA", "Reference buried ampacity", 100, unit="A", min=0.1),
    ],
    requires_project=False,
)
def soil_conditions(ctx, values: dict) -> dict:
    """Estimate buried-cable derating from relative soil thermal resistivity."""
    factor = math.sqrt(values["referenceResistivityKmW"] / values["siteResistivityKmW"])
    return result(
        summary={
            "soilCorrectionFactor": factor,
            "correctedAmpacityA": values["referenceAmpacityA"] * factor,
        },
        notes=[
            "This screening correction scales by the square root of reference-to-site resistivity; apply the cable manufacturer's burial model for depth, grouping, moisture and duct geometry."
        ],
    )


@feature(
    "mepElectricalCableSizing.asymmetricalPeak",
    "Asymmetrical Peak",
    part="mep",
    fields=[
        number("symmetricalFaultKa", "Initial symmetrical fault current", 10, unit="kA", min=0),
        number("resistanceOhm", "Source resistance", 0.01, unit="Ω", min=0),
        number("reactanceOhm", "Source reactance", 0.1, unit="Ω", min=0.001),
    ],
    requires_project=False,
)
def asymmetrical_peak(ctx, values: dict) -> dict:
    """Estimate the first peak asymmetrical short-circuit current."""
    ratio = values["resistanceOhm"] / values["reactanceOhm"]
    peak_factor = math.sqrt(2) * (1.02 + 0.98 * math.exp(-3 * ratio))
    peak = peak_factor * values["symmetricalFaultKa"]
    return result(
        summary={"peakAsymmetricalKa": peak, "peakFactor": peak_factor, "rxRatio": ratio},
        notes=[
            "Peak factor is estimated from the source R/X ratio; verify the calculation method and fault clearing conditions against the project protection study."
        ],
    )


@feature(
    "mepElectricalCableSizing.thdFactor",
    "THD Factor",
    part="mep",
    fields=[
        number("fundamentalCurrentA", "Fundamental current", 30, unit="A", min=0),
        number("thirdHarmonicA", "Third harmonic current", 8, unit="A", min=0),
        number("fifthHarmonicA", "Fifth harmonic current", 4, unit="A", min=0),
        number("baseAmpacityA", "Base conductor ampacity", 40, unit="A", min=0.1),
    ],
    requires_project=False,
)
def thd_factor(ctx, values: dict) -> dict:
    """Combine entered harmonic components and report neutral RMS current."""
    harmonics = math.sqrt(
        values["fundamentalCurrentA"] ** 2
        + values["thirdHarmonicA"] ** 2
        + values["fifthHarmonicA"] ** 2
    )
    thd = math.sqrt(values["thirdHarmonicA"] ** 2 + values["fifthHarmonicA"] ** 2) / max(
        values["fundamentalCurrentA"], 1e-12
    )
    return result(
        summary={
            "thdFraction": thd,
            "phaseRmsCurrentA": harmonics,
            "ampacityMarginA": values["baseAmpacityA"] - harmonics,
        },
        notes=[
            "RMS current combines orthogonal harmonic components; triplen harmonic neutral current can add arithmetically across phases and needs a separate neutral check."
        ],
    )


@feature(
    "mepElectricalCableSizing.skinEffectRatio",
    "Skin Effect Ratio",
    part="mep",
    fields=[
        number("acResistanceOhmKm", "AC conductor resistance", 0.95, unit="Ω/km", min=0),
        number("dcResistanceOhmKm", "DC conductor resistance", 0.8, unit="Ω/km", min=0.001),
        number("frequencyHz", "System frequency", 50, unit="Hz", min=1),
    ],
    requires_project=False,
)
def skin_effect_ratio(ctx, values: dict) -> dict:
    """Calculate the measured AC-to-DC resistance ratio at system frequency."""
    ratio = values["acResistanceOhmKm"] / values["dcResistanceOhmKm"]
    return result(
        summary={"acDcResistanceRatio": ratio, "additionalLossPercent": max(ratio - 1, 0) * 100},
        notes=[
            "Resistance ratio is calculated from supplied AC and DC conductor data; skin and proximity effects depend on conductor geometry and frequency."
        ],
    )


@feature(
    "mepElectricalCableSizing.conduitFillRatio",
    "Conduit Fill Ratio",
    part="mep",
    fields=[
        number("conduitInternalDiameterMm", "Conduit internal diameter", 32, unit="mm", min=1),
        number("cableOutsideDiameterMm", "Cable outside diameter", 8, unit="mm", min=0.1),
        number("cableCount", "Number of cables", 4, min=1),
        number("maximumFillFraction", "Project maximum fill fraction", 0.4, min=0.01, max=1),
    ],
    requires_project=False,
)
def conduit_fill_ratio(ctx, values: dict) -> dict:
    """Calculate total circular cable area and conduit fill percentage."""
    available = math.pi * values["conduitInternalDiameterMm"] ** 2 / 4
    occupied = int(values["cableCount"]) * math.pi * values["cableOutsideDiameterMm"] ** 2 / 4
    ratio = occupied / available
    return result(
        summary={
            "fillFraction": ratio,
            "fillPercent": ratio * 100,
            "passes": ratio <= values["maximumFillFraction"],
        },
        notes=[
            "Area-ratio screening assumes circular, undeformed cables and ignores pulling clearance and bend-radius constraints."
        ],
    )


@feature(
    "mepElectricalCableSizing.trayLoading",
    "Tray Loading",
    part="mep",
    fields=[
        number("cableMassKgPerM", "Combined cable mass per length", 18, unit="kg/m", min=0),
        number("trayWidthM", "Loaded tray width", 0.3, unit="m", min=0.01),
        number("supportSpanM", "Tray support span", 2, unit="m", min=0.1),
        number("allowableLineLoadKnM", "Tray allowable line load", 0.4, unit="kN/m", min=0.001),
    ],
    requires_project=False,
)
def tray_loading(ctx, values: dict) -> dict:
    """Check cable dead load per tray length against the entered capacity."""
    load = values["cableMassKgPerM"] * 9.80665 / 1000
    return result(
        summary={
            "cableLineLoadKnM": load,
            "supportReactionKn": load * values["supportSpanM"],
            "capacityPasses": load <= values["allowableLineLoadKnM"],
        },
        notes=[
            "Uniform dead load is cable mass per metre times gravity; compare with the tray manufacturer's span-specific load rating."
        ],
    )


@feature(
    "mepElectricalCableSizing.cableSeparation",
    "Cable Separation",
    part="mep",
    fields=[
        select("serviceA", "Service A", ["power", "data", "fireAlarm", "control"]),
        select("serviceB", "Service B", ["power", "data", "fireAlarm", "control"]),
        number("providedSeparationMm", "Provided separation", 150, unit="mm", min=0),
        number("requiredSeparationMm", "Project separation criterion", 100, unit="mm", min=0),
    ],
    requires_project=False,
)
def cable_separation(ctx, values: dict) -> dict:
    """Compare service separation with a project-defined minimum."""
    return result(
        summary={
            "servicePair": f"{values['serviceA']}/{values['serviceB']}",
            "passes": values["providedSeparationMm"] >= values["requiredSeparationMm"],
        },
        notes=[
            "Minimum separation is a project coordination criterion; verify electromagnetic compatibility, fire integrity and parallel-route length."
        ],
    )
