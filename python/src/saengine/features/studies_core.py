"""Studies - option management and whole-project engineering studies."""

from __future__ import annotations

import math
import random

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.studies_common import (
    interpolated_levels,
    numbers,
    records,
    study_path,
    write_json,
)


@feature(
    "studies.optionSets",
    "Option Sets",
    part="settings",
    fields=[
        text(
            "options",
            "Options JSON",
            '[{"name":"A","cost":100,"carbon":30},{"name":"B","cost":110,"carbon":25}]',
        ),
        text("groupKey", "Group by field", "scheme"),
    ],
    requires_project=False,
)
def option_sets(ctx: FeatureContext, values: dict) -> dict:
    """Group supplied design options by a shared classification field."""
    rows = records(values["options"], "design options")
    groups: dict[str, list[str]] = {}
    for index, row in enumerate(rows, 1):
        name = str(row.get("name") or f"Option {index}")
        groups.setdefault(str(row.get(values["groupKey"]) or "Unclassified"), []).append(name)
    return result(
        summary={"optionCount": len(rows), "setCount": len(groups)},
        tables=[
            table(
                "Option sets",
                [("set", "Set"), ("options", "Options")],
                [
                    {"set": key, "options": ", ".join(names)}
                    for key, names in sorted(groups.items())
                ],
            )
        ],
        notes=[
            "Groups are derived from the supplied option records; no project option files are modified."
        ],
    )


@feature(
    "studies.compareOptions",
    "Compare Options",
    part="settings",
    fields=[
        text(
            "options",
            "Options JSON",
            '[{"name":"A","cost":100,"carbon":30,"performance":80},{"name":"B","cost":110,"carbon":25,"performance":90}]',
        ),
        select(
            "metric",
            "Primary metric",
            [("cost", "Cost"), ("carbon", "Carbon"), ("performance", "Performance")],
            "cost",
        ),
    ],
    requires_project=False,
)
def compare_options(ctx: FeatureContext, values: dict) -> dict:
    """Rank supplied alternatives against a selected numeric metric."""
    rows = records(values["options"], "design options")
    key = values["metric"]
    ranked = []
    for row in rows:
        try:
            metric = float(row[key])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(f"Every option needs a numeric {key} value.") from error
        ranked.append(
            {
                "name": str(row.get("name", "Unnamed")),
                "metric": metric,
                "cost": row.get("cost"),
                "carbon": row.get("carbon"),
                "performance": row.get("performance"),
            }
        )
    ranked.sort(key=lambda row: row["metric"], reverse=key == "performance")
    return result(
        summary={"rankedOptions": len(ranked), "bestOption": ranked[0]["name"]},
        tables=[
            table(
                "Option comparison",
                [("rank", "Rank"), ("name", "Option"), ("metric", key.capitalize())],
                [dict(row, rank=i + 1) for i, row in enumerate(ranked)],
            )
        ],
        notes=[
            f"Lower {key} is preferred."
            if key != "performance"
            else "Higher performance is preferred."
        ],
    )


@feature(
    "studies.baselineOption",
    "Baseline Option",
    part="settings",
    fields=[
        text("options", "Available option names", "Baseline, Scheme A, Scheme B"),
        text("baseline", "Baseline name", "Baseline"),
    ],
    requires_project=False,
)
def baseline_option(ctx: FeatureContext, values: dict) -> dict:
    """Check that the nominated baseline exists in the option list."""
    names = [name.strip() for name in values["options"].split(",") if name.strip()]
    baseline = values["baseline"].strip()
    if not names or baseline not in names:
        raise FeatureInputError("Choose a baseline name from the comma-separated option list.")
    return result(
        summary={"baselineOption": baseline, "optionCount": len(names)},
        tables=[
            table(
                "Baseline membership",
                [("name", "Option"), ("role", "Role")],
                [
                    {"name": name, "role": "Baseline" if name == baseline else "Alternative"}
                    for name in names
                ],
            )
        ],
        notes=["The baseline is recorded in this study result."],
    )


@feature(
    "studies.mergeOptions",
    "Merge Options",
    part="settings",
    fields=[
        text(
            "options",
            "Option patches JSON",
            '[{"name":"Frame A","members":["B1","C1"],"cost":100},{"name":"Frame B","members":["B2"],"carbon":22}]',
        ),
        select(
            "conflict",
            "Conflict rule",
            [("later", "Later patch wins"), ("first", "First value wins")],
            "later",
        ),
    ],
    requires_project=False,
)
def merge_options(ctx: FeatureContext, values: dict) -> dict:
    """Merge selected option properties while retaining a trace of each source patch."""
    patches = records(values["options"], "option patches")
    merged: dict = {}
    for patch in patches:
        for key, value in patch.items():
            if key == "members" and isinstance(value, list):
                merged[key] = list(dict.fromkeys(merged.get(key, []) + value))
            elif key not in merged or values["conflict"] == "later":
                merged[key] = value
    return result(
        summary={"mergedProperties": len(merged), "sourceOptions": len(patches)},
        tables=[
            table(
                "Merged option properties",
                [("property", "Property"), ("value", "Merged value")],
                [{"property": key, "value": str(value)} for key, value in merged.items()],
            )
        ],
        notes=[
            "Member lists are unioned in source order; other conflicts follow the selected rule."
        ],
    )


@feature(
    "studies.activeOption",
    "Active Option",
    part="settings",
    fields=[text("option", "Active option", "Scheme A"), text("revision", "Option revision", "A")],
)
def active_option(ctx: FeatureContext, values: dict) -> dict:
    """Save the active option identifier and revision in the study output folder."""
    option = values["option"].strip()
    if not option:
        raise FeatureInputError("Enter the option to activate.")
    payload = {"activeOption": option, "revision": values["revision"].strip()}
    path = write_json(ctx, study_path("active-option"), payload)
    return result(
        summary={"activeOption": option, "outputPath": path},
        notes=[f"Active option selection saved to {path}."],
    )


@feature(
    "studies.variantGenerator",
    "Variant Generator",
    part="settings",
    fields=[
        text("parameter", "Parameter name", "baySpacing"),
        number("start", "Start value", 5.0),
        number("end", "End value", 8.0),
        number("count", "Variant count", 4, min=2, max=100),
    ],
)
def variant_generator(ctx: FeatureContext, values: dict) -> dict:
    """Generate a deterministic set of parameter variants over an inclusive interval."""
    levels = interpolated_levels(values["start"], values["end"], int(values["count"]))
    rows = [
        {"variant": f"V{i:03}", "parameter": values["parameter"], "value": v}
        for i, v in enumerate(levels, 1)
    ]
    return result(
        summary={"variantCount": len(rows), "parameter": values["parameter"]},
        tables=[
            table(
                "Generated variants",
                [("variant", "Variant"), ("parameter", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Values are evenly spaced, including both range limits."],
    )


@feature(
    "studies.parameterSweep",
    "Parameter Sweep",
    part="settings",
    fields=[
        text("parameter", "Parameter", "span"),
        number("start", "Start value", 4.0),
        number("stop", "Stop value", 10.0),
        number("step", "Increment", 2.0),
    ],
)
def parameter_sweep(ctx: FeatureContext, values: dict) -> dict:
    """List parameter values at a fixed increment, retaining the requested end when aligned."""
    start, stop, step = values["start"], values["stop"], values["step"]
    if step <= 0 or stop < start:
        raise FeatureInputError("Use a positive increment and a stop value at or above the start.")
    count = math.floor((stop - start) / step + 1e-10) + 1
    if count > 1000:
        raise FeatureInputError("A sweep may contain at most 1000 values.")
    rows = [
        {"index": i + 1, "parameter": values["parameter"], "value": start + i * step}
        for i in range(count)
    ]
    return result(
        summary={"stepCount": count, "lastValue": rows[-1]["value"]},
        tables=[
            table(
                "Parameter sweep",
                [("index", "Step"), ("parameter", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=["The stop value is included only when it lies on the increment sequence."],
    )


@feature(
    "studies.scenarioTable",
    "Scenario Table",
    part="settings",
    fields=[
        text(
            "scenarios",
            "Scenario records",
            '[{"name":"Base","spanM":6,"loadKn":20},{"name":"Alt","spanM":7,"loadKn":24}]',
        )
    ],
    requires_project=False,
)
def scenario_table(ctx: FeatureContext, values: dict) -> dict:
    """Validate and tabulate scenario records without hiding different input columns."""
    rows = records(values["scenarios"], "scenarios")
    columns = list(dict.fromkeys(key for row in rows for key in row))
    output = [{key: row.get(key) for key in columns} for row in rows]
    return result(
        summary={"scenarioCount": len(output), "inputColumnCount": len(columns)},
        tables=[
            table("Scenarios", [(key, key.replace("_", " ").title()) for key in columns], output)
        ],
        notes=[
            "Scenario values are shown as supplied; units belong in the field names, for example spanM."
        ],
    )


@feature(
    "studies.windTunnelStudy",
    "Wind Tunnel Study",
    part="settings",
    fields=[
        number("speed", "Reference wind speed", 30, unit="m/s", min=0),
        number("height", "Height above ground", 20, unit="m", min=0.1),
        number("referenceHeight", "Reference height", 10, unit="m", min=0.1),
        number("exponent", "Profile exponent", 0.16, min=0, max=1),
        number("pressureCoefficient", "Pressure coefficient", 1.0),
        number("density", "Air density", 1.225, unit="kg/m³", min=0.1),
    ],
)
def wind_tunnel_study(ctx: FeatureContext, values: dict) -> dict:
    """Estimate mean velocity pressure at a target height using a power-law profile."""
    speed = values["speed"] * (values["height"] / values["referenceHeight"]) ** values["exponent"]
    pressure = 0.5 * values["density"] * speed**2 / 1000
    net = pressure * values["pressureCoefficient"]
    return result(
        summary={
            "velocityAtHeightMPerS": speed,
            "velocityPressureKpa": pressure,
            "netPressureKpa": net,
        },
        notes=[
            "Power-law mean wind profile and Bernoulli dynamic pressure; turbulence spectra, terrain transitions and local pressure coefficients require measured or separately justified inputs."
        ],
    )


@feature(
    "studies.blastStudy",
    "Blast Study",
    part="settings",
    fields=[
        number("peakPressure", "Measured peak overpressure", 25, unit="kPa", min=0),
        number("positiveDuration", "Positive phase duration", 0.12, unit="s", min=0),
        number("tributaryArea", "Loaded area", 10, unit="m²", min=0.01),
        number("mass", "Supported mass", 5000, unit="kg", min=1),
    ],
)
def blast_study(ctx: FeatureContext, values: dict) -> dict:
    """Convert a supplied triangular blast pulse into impulse and a rigid-body velocity increment."""
    impulse = 0.5 * values["peakPressure"] * 1000 * values["positiveDuration"]
    force = values["peakPressure"] * values["tributaryArea"]
    delta_v = impulse * values["tributaryArea"] / values["mass"]
    return result(
        summary={"impulsePaS": impulse, "peakForceKn": force, "velocityChangeMPerS": delta_v},
        notes=[
            "The user-supplied positive phase is approximated as a triangular pressure-time pulse. This is a load conversion, not a blast propagation prediction."
        ],
    )


@feature(
    "studies.dynamicResponse",
    "Dynamic Response",
    part="settings",
    fields=[
        number("mass", "Effective mass", 10000, unit="kg", min=1),
        number("stiffness", "Lateral stiffness", 20000, unit="kN/m", min=0.001),
        number("damping", "Damping ratio", 0.05, min=0, max=0.99),
        number("excitationHz", "Excitation frequency", 1, unit="Hz", min=0),
        number("force", "Harmonic force amplitude", 10, unit="kN", min=0),
    ],
)
def dynamic_response(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the steady-state response of a damped single-degree-of-freedom oscillator."""
    natural = math.sqrt(values["stiffness"] * 1000 / values["mass"]) / (2 * math.pi)
    ratio = values["excitationHz"] / natural
    denominator = math.sqrt((1 - ratio**2) ** 2 + (2 * values["damping"] * ratio) ** 2)
    magnification = 1 / denominator if denominator > 1e-12 else math.inf
    displacement = values["force"] * 1000 / (values["stiffness"] * 1000) * magnification
    return result(
        summary={
            "naturalFrequencyHz": natural,
            "frequencyRatio": ratio,
            "dynamicMagnification": magnification,
            "displacementMm": displacement * 1000,
        },
        notes=[
            "Linear steady-state harmonic response of an SDOF oscillator; stiffness is the tangent stiffness and the response excludes nonlinear yielding."
        ],
    )


@feature(
    "studies.seismicStudy",
    "Seismic Study",
    part="settings",
    fields=[
        text("floorMasses", "Floor masses from base, kg", "100000, 90000, 80000"),
        text("floorHeights", "Floor elevations from base, m", "4, 8, 12"),
        number("spectralAcceleration", "Spectral acceleration", 0.4, unit="g", min=0),
        number("heightExponent", "Vertical distribution exponent", 1.0, min=0, max=4),
    ],
)
def seismic_study(ctx: FeatureContext, values: dict) -> dict:
    """Distribute an input spectral base shear to floors by mass times elevation power."""
    masses, heights = (
        numbers(values["floorMasses"], "floor masses"),
        numbers(values["floorHeights"], "floor heights"),
    )
    if len(masses) != len(heights) or any(m <= 0 for m in masses) or any(h <= 0 for h in heights):
        raise FeatureInputError("Provide matching positive floor masses and elevations.")
    weights = [m * h ** values["heightExponent"] for m, h in zip(masses, heights, strict=True)]
    base_shear = sum(masses) * 9.80665 * values["spectralAcceleration"] / 1000
    rows = [
        {
            "floor": i + 1,
            "height": h,
            "mass": m,
            "weightShare": w / sum(weights),
            "lateralForce": base_shear * w / sum(weights),
        }
        for i, (h, m, w) in enumerate(zip(heights, masses, weights, strict=True))
    ]
    return result(
        summary={"baseShearKn": base_shear, "floorCount": len(rows)},
        tables=[
            table(
                "Floor force distribution",
                [
                    ("floor", "Floor"),
                    ("height", "Height", "m"),
                    ("mass", "Mass", "kg"),
                    ("weightShare", "Shear share"),
                    ("lateralForce", "Lateral force", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Equivalent static inertial forces from the supplied spectral acceleration; the vertical exponent is an explicit study assumption, not a code-prescribed distribution."
        ],
    )


@feature(
    "studies.costLifeCycle",
    "Cost Life Cycle",
    part="settings",
    fields=[
        number("initialCost", "Initial cost", 1000000, unit="currency", min=0),
        number("annualCost", "Annual operating cost", 25000, unit="currency/year", min=0),
        number("years", "Study period", 50, unit="year", min=1, max=200),
        number("discountRate", "Real discount rate", 0.04, min=0, max=1),
        number("replacementCost", "Midlife replacement cost", 0, unit="currency", min=0),
    ],
)
def cost_life_cycle(ctx: FeatureContext, values: dict) -> dict:
    """Compute present-value life-cycle cost with a uniform annual series and one midpoint renewal."""
    years = int(values["years"])
    rate = values["discountRate"]
    pv_annuity = (
        values["annualCost"] * years
        if rate == 0
        else values["annualCost"] * (1 - (1 + rate) ** -years) / rate
    )
    replacement_year = years // 2
    renewal = values["replacementCost"] / (1 + rate) ** replacement_year
    return result(
        summary={
            "initialCost": values["initialCost"],
            "presentValueOperatingCost": pv_annuity,
            "presentValueReplacementCost": renewal,
            "lifeCycleCost": values["initialCost"] + pv_annuity + renewal,
        },
        tables=[
            table(
                "Life-cycle cost components",
                [("component", "Component"), ("presentValue", "Present value", "currency")],
                [
                    {"component": "Initial", "presentValue": values["initialCost"]},
                    {"component": "Operations", "presentValue": pv_annuity},
                    {"component": "Midlife renewal", "presentValue": renewal},
                ],
            )
        ],
        notes=[
            "Constant end-of-year operating costs and a single renewal at the integer midpoint; taxes, inflation and residual value are excluded."
        ],
    )


@feature(
    "studies.demolitionStudy",
    "Demolition Study",
    part="settings",
    fields=[
        text(
            "quantities",
            "Material quantities",
            '[{"material":"concrete","massTonnes":120,"recoveryRate":0.8,"factorKgCo2PerTonne":10},{"material":"steel","massTonnes":8,"recoveryRate":0.95,"factorKgCo2PerTonne":25}]',
        )
    ],
    requires_project=False,
)
def demolition_study(ctx: FeatureContext, values: dict) -> dict:
    """Estimate recoverable mass and residual disposal mass from material quantities."""
    rows = records(values["quantities"], "demolition quantities")
    output = []
    for row in rows:
        try:
            mass, recovery = float(row["massTonnes"]), float(row["recoveryRate"])
            factor = float(row.get("factorKgCo2PerTonne", 0))
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each material needs massTonnes and recoveryRate, with an optional carbon factor."
            ) from error
        if mass < 0 or not 0 <= recovery <= 1:
            raise FeatureInputError(
                "Mass must be non-negative and recoveryRate must be between 0 and 1."
            )
        output.append(
            {
                "material": row.get("material", "Unspecified"),
                "mass": mass,
                "recovered": mass * recovery,
                "disposal": mass * (1 - recovery),
                "disposalCarbon": mass * (1 - recovery) * factor,
            }
        )
    return result(
        summary={
            "massTonnes": sum(r["mass"] for r in output),
            "recoveredTonnes": sum(r["recovered"] for r in output),
            "disposalTonnes": sum(r["disposal"] for r in output),
            "disposalCarbonKgCo2": sum(r["disposalCarbon"] for r in output),
        },
        tables=[
            table(
                "Demolition material balance",
                [
                    ("material", "Material"),
                    ("mass", "Mass", "t"),
                    ("recovered", "Recovered", "t"),
                    ("disposal", "Disposal", "t"),
                    ("disposalCarbon", "Disposal carbon", "kg CO2e"),
                ],
                output,
            )
        ],
        notes=["Recovery and disposal carbon factors are user-supplied scenario inputs."],
    )


@feature(
    "studies.maintenanceModel",
    "Maintenance Model",
    part="settings",
    fields=[
        number("annualInspection", "Annual inspection cost", 2000, unit="currency/year", min=0),
        number("repairCost", "Repair event cost", 15000, unit="currency", min=0),
        number("interval", "Repair interval", 12, unit="year", min=1),
        number("life", "Analysis life", 60, unit="year", min=1, max=200),
        number("discountRate", "Discount rate", 0.03, min=0, max=1),
    ],
)
def maintenance_model(ctx: FeatureContext, values: dict) -> dict:
    """Discount a recurring inspection stream and periodic repair events over the asset life."""
    life, interval, rate = int(values["life"]), int(values["interval"]), values["discountRate"]
    inspections = sum(
        values["annualInspection"] / (1 + rate) ** year for year in range(1, life + 1)
    )
    years = list(range(interval, life + 1, interval))
    repairs = sum(values["repairCost"] / (1 + rate) ** year for year in years)
    rows = [
        {
            "year": year,
            "repairCost": values["repairCost"],
            "presentValue": values["repairCost"] / (1 + rate) ** year,
        }
        for year in years
    ]
    return result(
        summary={
            "inspectionPresentValue": inspections,
            "repairPresentValue": repairs,
            "totalPresentValue": inspections + repairs,
            "repairEvents": len(years),
        },
        tables=[
            table(
                "Repair events",
                [
                    ("year", "Year"),
                    ("repairCost", "Repair cost", "currency"),
                    ("presentValue", "Present value", "currency"),
                ],
                rows,
            )
        ],
        notes=[
            "Inspection occurs at each year-end; repairs occur at integer interval multiples. Costs are constant in real terms."
        ],
    )


@feature(
    "studies.monteCarloStudy",
    "Monte Carlo Study",
    part="settings",
    fields=[
        number("mean", "Mean quantity", 100, unit="kN"),
        number("coefficientVariation", "Coefficient of variation", 0.1, min=0, max=2),
        number("limit", "Limit state threshold", 120, unit="kN"),
        number("samples", "Simulation samples", 10000, min=100, max=200000),
        number("seed", "Repeatable seed", 417, min=0, max=2147483647),
    ],
)
def monte_carlo_study(ctx: FeatureContext, values: dict) -> dict:
    """Estimate threshold exceedance by deterministic Monte Carlo sampling of a normal variable."""
    rng = random.Random(int(values["seed"]))
    sigma = values["mean"] * values["coefficientVariation"]
    samples = (
        [rng.gauss(values["mean"], sigma) for _ in range(int(values["samples"]))]
        if sigma
        else [values["mean"]] * int(values["samples"])
    )
    exceed = sum(sample > values["limit"] for sample in samples)
    ordered = sorted(samples)
    q95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
    return result(
        summary={
            "sampleCount": len(samples),
            "sampleMean": sum(samples) / len(samples),
            "sampleStd": math.sqrt(
                sum((x - sum(samples) / len(samples)) ** 2 for x in samples) / (len(samples) - 1)
            ),
            "exceedanceProbability": exceed / len(samples),
            "q95": q95,
        },
        notes=[
            "Normal input distribution with user-selected coefficient of variation; the seed makes the result reproducible. Exceedance is a model estimate, not a reliability certification."
        ],
    )


@feature(
    "studies.structuralReliability",
    "Structural Reliability",
    part="settings",
    fields=[
        number("capacityMean", "Capacity mean", 500, unit="kN", min=0.001),
        number("capacityStd", "Capacity standard deviation", 50, unit="kN", min=0),
        number("demandMean", "Demand mean", 350, unit="kN", min=0),
        number("demandStd", "Demand standard deviation", 40, unit="kN", min=0),
    ],
)
def structural_reliability(ctx: FeatureContext, values: dict) -> dict:
    """Estimate a normal-normal reliability index and failure probability for capacity minus demand."""
    sigma = math.hypot(values["capacityStd"], values["demandStd"])
    if sigma == 0:
        beta = math.inf if values["capacityMean"] >= values["demandMean"] else -math.inf
        probability = 0.0 if beta > 0 else 1.0
    else:
        beta = (values["capacityMean"] - values["demandMean"]) / sigma
        probability = 0.5 * math.erfc(beta / math.sqrt(2))
    return result(
        summary={"reliabilityIndex": beta, "failureProbability": probability, "combinedStd": sigma},
        notes=[
            "First-order reliability for independent normally distributed capacity and demand; correlation, non-normal tails and model uncertainty are not included."
        ],
    )


@feature(
    "studies.robustnessCheck",
    "Robustness Check",
    part="settings",
    fields=[
        number("alternatePathCapacity", "Alternate-path capacity", 600, unit="kN", min=0),
        number("lostSupportDemand", "Demand after support loss", 420, unit="kN", min=0),
        number("redundantPaths", "Independent load paths", 2, min=1, max=100),
    ],
)
def robustness_check(ctx: FeatureContext, values: dict) -> dict:
    """Compare post-removal demand with alternate-path capacity and report reserve ratio."""
    reserve = values["alternatePathCapacity"] - values["lostSupportDemand"]
    ratio = (
        values["alternatePathCapacity"] / values["lostSupportDemand"]
        if values["lostSupportDemand"]
        else math.inf
    )
    return result(
        summary={
            "reserveKn": reserve,
            "capacityDemandRatio": ratio,
            "pathCount": int(values["redundantPaths"]),
            "passesCapacityComparison": reserve >= 0,
        },
        notes=[
            "Static capacity comparison for the user-defined support-removal scenario; dynamic amplification and load redistribution must be established separately."
        ],
    )


@feature(
    "studies.feasibilityCheck",
    "Feasibility Check",
    part="settings",
    fields=[
        number("requiredArea", "Required floor area", 5000, unit="m²", min=0),
        number("availableArea", "Available floor area", 6200, unit="m²", min=0),
        number("maxHeight", "Height limit", 45, unit="m", min=0),
        number("proposedHeight", "Proposed height", 38, unit="m", min=0),
        number("budget", "Budget", 12000000, unit="currency", min=0),
        number("estimate", "Cost estimate", 11500000, unit="currency", min=0),
    ],
)
def feasibility_check(ctx: FeatureContext, values: dict) -> dict:
    """Check area, height and budget requirements against supplied project limits."""
    checks = [
        (
            "area",
            values["requiredArea"] <= values["availableArea"],
            values["requiredArea"],
            values["availableArea"],
        ),
        (
            "height",
            values["proposedHeight"] <= values["maxHeight"],
            values["proposedHeight"],
            values["maxHeight"],
        ),
        ("budget", values["estimate"] <= values["budget"], values["estimate"], values["budget"]),
    ]
    return result(
        summary={
            "feasible": all(c[1] for c in checks),
            "failedChecks": sum(not c[1] for c in checks),
        },
        tables=[
            table(
                "Feasibility limits",
                [
                    ("check", "Check"),
                    ("proposed", "Proposed"),
                    ("limit", "Limit"),
                    ("passes", "Passes"),
                ],
                [
                    {"check": name, "proposed": proposed, "limit": limit, "passes": passed}
                    for name, passed, proposed, limit in checks
                ],
            )
        ],
        notes=[
            "This screens only the three supplied constraints; planning, ground, services and procurement constraints are outside this calculation."
        ],
    )


@feature(
    "studies.constructability",
    "Constructability",
    part="settings",
    fields=[
        number("liftCapacity", "Crane lift capacity", 12, unit="t", min=0),
        number("elementMass", "Heaviest element mass", 8, unit="t", min=0),
        number("routeWidth", "Access route width", 5, unit="m", min=0),
        number("requiredWidth", "Required transport width", 4, unit="m", min=0),
        number("clearance", "Headroom clearance", 6, unit="m", min=0),
        number("requiredClearance", "Transport height", 5, unit="m", min=0),
    ],
)
def constructability(ctx: FeatureContext, values: dict) -> dict:
    """Screen a lift and delivery route against supplied capacity and clearance limits."""
    checks = [
        {"item": "Lift", "available": values["liftCapacity"], "required": values["elementMass"]},
        {
            "item": "Route width",
            "available": values["routeWidth"],
            "required": values["requiredWidth"],
        },
        {
            "item": "Headroom",
            "available": values["clearance"],
            "required": values["requiredClearance"],
        },
    ]
    for row in checks:
        row["utilization"] = row["required"] / row["available"] if row["available"] else math.inf
        row["passes"] = row["available"] >= row["required"]
    return result(
        summary={
            "constructableByScreen": all(row["passes"] for row in checks),
            "limitingUtilization": max(row["utilization"] for row in checks),
        },
        tables=[
            table(
                "Access and lifting checks",
                [
                    ("item", "Check"),
                    ("available", "Available"),
                    ("required", "Required"),
                    ("utilization", "Utilization"),
                    ("passes", "Passes"),
                ],
                checks,
            )
        ],
        notes=[
            "A planning-level envelope check; crane capacity at working radius, rigging, turning paths and temporary works need project-specific confirmation."
        ],
    )


@feature(
    "studies.siteLogistics",
    "Site Logistics",
    part="settings",
    fields=[
        number("siteLength", "Site length", 100, unit="m", min=0.1),
        number("siteWidth", "Site width", 60, unit="m", min=0.1),
        number("craneRadius", "Crane working radius", 45, unit="m", min=0.1),
        number("laydownArea", "Laydown area", 800, unit="m²", min=0),
        number("accessWidth", "Delivery access width", 5, unit="m", min=0),
    ],
)
def site_logistics(ctx: FeatureContext, values: dict) -> dict:
    """Estimate rectangular site coverage by one central crane and check laydown share."""
    site_area = values["siteLength"] * values["siteWidth"]
    covered = min(site_area, math.pi * values["craneRadius"] ** 2)
    return result(
        summary={
            "siteAreaM2": site_area,
            "craneCoverageM2": covered,
            "coverageRatio": covered / site_area,
            "laydownRatio": values["laydownArea"] / site_area,
            "deliveryAccessWidthM": values["accessWidth"],
        },
        notes=[
            "Coverage is the intersection-free area of a circle and a rectangular site capped by the site's area; crane location, obstructions and reach at load are not modeled."
        ],
    )
