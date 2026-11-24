"""Studies Risk - event registers, probabilistic risk and consequence screening."""

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
from saengine.features.studies_common import records


@feature(
    "studiesRisk.addRisk",
    "Add Risk",
    part="settings",
    fields=[
        text(
            "risks",
            "Risk register items",
            '[{"id":"R-01","event":"Late steel delivery","probability":0.2,"consequenceCurrency":50000,"owner":"Procurement"}]',
        )
    ],
    requires_project=False,
)
def add_risk(ctx: FeatureContext, values: dict) -> dict:
    """Validate and tabulate a project risk register with expected-loss values."""
    rows = records(values["risks"], "risk register")
    output = []
    for row in rows:
        try:
            probability, impact = float(row["probability"]), float(row["consequenceCurrency"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Every risk needs probability and consequenceCurrency values."
            ) from error
        if not 0 <= probability <= 1 or impact < 0:
            raise FeatureInputError(
                "Risk probability must be from 0 to 1 and consequence must be non-negative."
            )
        output.append(
            {
                "id": row.get("id", "Risk"),
                "event": row.get("event", "Event"),
                "probability": probability,
                "consequenceCurrency": impact,
                "expectedLossCurrency": probability * impact,
                "owner": row.get("owner", "Unassigned"),
            }
        )
    return result(
        summary={
            "riskCount": len(output),
            "totalExpectedLossCurrency": sum(row["expectedLossCurrency"] for row in output),
        },
        tables=[
            table(
                "Risk register",
                [
                    ("id", "Id"),
                    ("event", "Event"),
                    ("probability", "Probability"),
                    ("consequenceCurrency", "Consequence", "currency"),
                    ("expectedLossCurrency", "Expected loss", "currency"),
                    ("owner", "Owner"),
                ],
                output,
            )
        ],
        notes=[
            "Expected loss is probability × consequence for each stated risk; dependencies and portfolio correlation are not considered."
        ],
    )


@feature(
    "studiesRisk.likelihoodRating",
    "Likelihood Rating",
    part="settings",
    fields=[number("annualProbability", "Annual event probability", 0.1, min=0, max=1)],
    requires_project=False,
)
def likelihood_rating(ctx: FeatureContext, values: dict) -> dict:
    """Assign a descriptive five-band likelihood rating to an annual event probability."""
    p = values["annualProbability"]
    label = (
        "rare"
        if p < 0.01
        else "unlikely"
        if p < 0.05
        else "possible"
        if p < 0.2
        else "likely"
        if p < 0.5
        else "almost certain"
    )
    return result(
        summary={"annualProbability": p, "rating": label},
        tables=[
            table(
                "Likelihood bands",
                [
                    ("rating", "Rating"),
                    ("lowerProbability", "Lower bound"),
                    ("upperProbability", "Upper bound"),
                ],
                [
                    {"rating": "rare", "lowerProbability": 0, "upperProbability": 0.01},
                    {"rating": "unlikely", "lowerProbability": 0.01, "upperProbability": 0.05},
                    {"rating": "possible", "lowerProbability": 0.05, "upperProbability": 0.2},
                    {"rating": "likely", "lowerProbability": 0.2, "upperProbability": 0.5},
                    {"rating": "almost certain", "lowerProbability": 0.5, "upperProbability": 1},
                ],
            )
        ],
        notes=[
            "Rating bands are a transparent project scale defined here, not a prescribed risk standard."
        ],
    )


@feature(
    "studiesRisk.impactRating",
    "Impact Rating",
    part="settings",
    fields=[
        number("directCost", "Direct consequence", 100000, unit="currency", min=0),
        number("duration", "Delay consequence", 30, unit="day", min=0),
        number("costPerDay", "Delay cost per day", 1000, unit="currency/day", min=0),
    ],
    requires_project=False,
)
def impact_rating(ctx: FeatureContext, values: dict) -> dict:
    """Combine direct cost and time-related cost into a five-level project impact rating."""
    delay_cost = values["duration"] * values["costPerDay"]
    total = values["directCost"] + delay_cost
    rating = (
        "minor"
        if total < 10000
        else "moderate"
        if total < 50000
        else "major"
        if total < 250000
        else "severe"
        if total < 1_000_000
        else "critical"
    )
    return result(
        summary={"delayCost": delay_cost, "combinedCost": total, "rating": rating},
        notes=[
            "The cost bands are explicit screening thresholds; safety, service disruption and reputational consequences need separate ratings."
        ],
    )


@feature(
    "studiesRisk.riskScore",
    "Risk Score",
    part="settings",
    fields=[
        number("probability", "Event probability", 0.2, min=0, max=1),
        number("impact", "Impact score", 4, min=0),
        number("exposure", "Exposure factor", 1, min=0),
    ],
    requires_project=False,
)
def risk_score(ctx: FeatureContext, values: dict) -> dict:
    """Calculate probability-weighted risk score from declared probability, impact and exposure."""
    score = values["probability"] * values["impact"] * values["exposure"]
    return result(
        summary={
            "riskScore": score,
            "probability": values["probability"],
            "impact": values["impact"],
            "exposure": values["exposure"],
        },
        notes=[
            "The score is the product of the three supplied factors and has no universal interpretation without the project's scoring scale."
        ],
    )


@feature(
    "studiesRisk.monteCarlo",
    "Monte Carlo",
    part="settings",
    fields=[
        text(
            "events",
            "Risk event distributions",
            '[{"name":"Delay","probability":0.25,"costLow":20000,"costMode":50000,"costHigh":100000},{"name":"Repair","probability":0.1,"costLow":10000,"costMode":30000,"costHigh":60000}]',
        ),
        number("iterations", "Simulation trials", 10000, min=100, max=200000),
        number("seed", "Seed", 1729, min=0, max=2147483647),
    ],
    requires_project=False,
)
def monte_carlo(ctx: FeatureContext, values: dict) -> dict:
    """Simulate total risk cost from Bernoulli occurrence and triangular loss distributions."""
    events = records(values["events"], "risk events")
    rng, trials = random.Random(int(values["seed"])), int(values["iterations"])
    costs = [0.0] * trials
    for event in events:
        try:
            probability, low, mode, high = (
                float(event["probability"]),
                float(event["costLow"]),
                float(event["costMode"]),
                float(event["costHigh"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each event needs probability, costLow, costMode and costHigh."
            ) from error
        if not 0 <= probability <= 1 or not low <= mode <= high:
            raise FeatureInputError(
                "Use a probability between 0 and 1 and triangular costs with low ≤ mode ≤ high."
            )
        for i in range(trials):
            if rng.random() < probability:
                costs[i] += rng.triangular(low, high, mode)
    ordered = sorted(costs)
    mean = sum(costs) / trials
    return result(
        summary={
            "trialCount": trials,
            "meanLossCurrency": mean,
            "medianLossCurrency": ordered[trials // 2],
            "p90LossCurrency": ordered[math.ceil(0.9 * trials) - 1],
            "probabilityOfLoss": sum(cost > 0 for cost in costs) / trials,
        },
        tables=[
            table(
                "Risk event inputs",
                [
                    ("name", "Event"),
                    ("probability", "Probability"),
                    ("costLow", "Low", "currency"),
                    ("costMode", "Mode", "currency"),
                    ("costHigh", "High", "currency"),
                ],
                events,
            )
        ],
        notes=[
            "Independent Bernoulli event occurrence and triangular loss conditional on occurrence; correlations between risks are not represented."
        ],
    )


@feature(
    "studiesRisk.iterationCount",
    "Iteration Count",
    part="settings",
    fields=[
        number("eventProbability", "Expected event probability", 0.05, min=0.000001, max=0.999999),
        number("relativeHalfWidth", "Target relative confidence half-width", 0.1, min=0.001, max=1),
        number("confidenceZ", "Normal confidence multiplier", 1.96, min=0.1, max=5),
    ],
    requires_project=False,
)
def iteration_count(ctx: FeatureContext, values: dict) -> dict:
    """Estimate Bernoulli trials required for a normal-approximation probability interval."""
    p, z, r = values["eventProbability"], values["confidenceZ"], values["relativeHalfWidth"]
    n = math.ceil(z**2 * (1 - p) / (r**2 * p))
    return result(
        summary={"recommendedTrials": n, "eventProbability": p, "targetRelativeHalfWidth": r},
        notes=[
            "Uses n ≈ z²(1−p)/(r²p) for a two-sided normal-approximation interval; rare-event variance reduction and exact binomial intervals are not included."
        ],
    )


@feature(
    "studiesRisk.distributionType",
    "Distribution Type",
    part="settings",
    fields=[
        select(
            "distribution",
            "Input distribution",
            [("normal", "Normal"), ("uniform", "Uniform"), ("triangular", "Triangular")],
            "triangular",
        ),
        number("low", "Lower bound", 0),
        number("mode", "Mode or mean", 10),
        number("high", "Upper bound", 20),
        number("samples", "Display samples", 11, min=3, max=101),
    ],
    requires_project=False,
)
def distribution_type(ctx: FeatureContext, values: dict) -> dict:
    """Describe central distribution properties and quantile points for a selected risk input."""
    low, mode, high = values["low"], values["mode"], values["high"]
    if high <= low or not low <= mode <= high:
        raise FeatureInputError(
            "Use a maximum above the minimum and a mode or mean within the bounds."
        )
    if values["distribution"] == "triangular":
        mean, variance = (
            (low + mode + high) / 3,
            (low**2 + mode**2 + high**2 - low * mode - low * high - mode * high) / 18,
        )
        quantiles = [
            low + math.sqrt(q * (high - low) * (mode - low))
            if q < (mode - low) / (high - low)
            else high - math.sqrt((1 - q) * (high - low) * (high - mode))
            for q in [i / (int(values["samples"]) - 1) for i in range(int(values["samples"]))]
        ]
    elif values["distribution"] == "uniform":
        mean, variance = (low + high) / 2, (high - low) ** 2 / 12
        quantiles = [
            low + i * (high - low) / (int(values["samples"]) - 1)
            for i in range(int(values["samples"]))
        ]
    else:
        mean, variance = mode, ((high - low) / 6) ** 2
        quantiles = [
            mean + math.sqrt(variance) * _normal_quantile(i / (int(values["samples"]) - 1))
            for i in range(int(values["samples"]))
        ]
    return result(
        summary={
            "distribution": values["distribution"],
            "mean": mean,
            "standardDeviation": math.sqrt(variance),
            "minimum": low,
            "maximum": high,
        },
        tables=[
            table(
                "Distribution quantile points",
                [("probability", "Probability"), ("value", "Value")],
                [
                    {"probability": i / (len(quantiles) - 1), "value": value}
                    for i, value in enumerate(quantiles)
                ],
            )
        ],
        notes=[
            "Normal uses mean = mode input and standard deviation = range/6; quantiles use an inverse-normal approximation."
        ],
    )


def _normal_quantile(probability: float) -> float:
    """Acklam's rational approximation to the standard-normal inverse CDF."""
    if probability <= 0:
        return -3.5
    if probability >= 1:
        return 3.5
    a = (
        -39.6968302866538,
        220.946098424521,
        -275.928510446969,
        138.357751867269,
        -30.6647980661472,
        2.50662827745924,
    )
    b = (
        -54.4760987982241,
        161.585836858041,
        -155.698979859887,
        66.8013118877197,
        -13.2806815528857,
    )
    c = (
        -0.00778489400243029,
        -0.322396458041136,
        -2.40075827716184,
        -2.54973253934373,
        4.37466414146497,
        2.93816398269878,
    )
    d = (0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742)
    if probability < 0.02425:
        q = math.sqrt(-2 * math.log(probability))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if probability > 0.97575:
        return -_normal_quantile(1 - probability)
    q = probability - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


@feature(
    "studiesRisk.runSimulation",
    "Run Simulation",
    part="settings",
    fields=[
        select(
            "distribution",
            "Demand uncertainty",
            [("normal", "Normal"), ("uniform", "Uniform")],
            "normal",
        ),
        number("meanDemand", "Mean demand", 400, unit="kN", min=0),
        number("standardDeviation", "Demand standard deviation", 40, unit="kN", min=0),
        number("capacity", "Capacity threshold", 500, unit="kN", min=0),
        number("iterations", "Trials", 20000, min=100, max=200000),
        number("seed", "Seed", 241, min=0, max=2147483647),
    ],
    requires_project=False,
)
def run_simulation(ctx: FeatureContext, values: dict) -> dict:
    """Run a reproducible demand-capacity failure simulation with declared normal or uniform demand."""
    rng, n = random.Random(int(values["seed"])), int(values["iterations"])
    sigma = values["standardDeviation"]
    if values["distribution"] == "uniform" and sigma:
        half_width = math.sqrt(3) * sigma
        samples = [
            rng.uniform(values["meanDemand"] - half_width, values["meanDemand"] + half_width)
            for _ in range(n)
        ]
    else:
        samples = (
            [rng.gauss(values["meanDemand"], sigma) for _ in range(n)]
            if sigma
            else [values["meanDemand"]] * n
        )
    failed = sum(sample > values["capacity"] for sample in samples)
    return result(
        summary={
            "iterationCount": n,
            "failures": failed,
            "estimatedFailureProbability": failed / n,
            "capacityKn": values["capacity"],
        },
        notes=[
            "Demand is sampled independently from the chosen distribution and capacity is treated as deterministic."
        ],
    )


@feature(
    "studiesRisk.sensitivityStudy",
    "Sensitivity Study",
    part="settings",
    fields=[
        text(
            "data",
            "Input-output response records",
            '[{"x":1,"y":10},{"x":2,"y":13},{"x":3,"y":16}]',
        ),
        text("response", "Response column", "y"),
    ],
    requires_project=False,
)
def sensitivity_study(ctx: FeatureContext, values: dict) -> dict:
    """Rank measured risk factors by absolute correlation with a selected outcome."""
    rows = records(values["data"], "risk sensitivity data")
    try:
        ys = [float(row[values["response"]]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise FeatureInputError("Every data row needs the selected numeric response.") from error
    my = sum(ys) / len(ys)
    scores = []
    for key in rows[0]:
        if key == values["response"]:
            continue
        try:
            xs = [float(row[key]) for row in rows]
        except (KeyError, TypeError, ValueError):
            continue
        mx = sum(xs) / len(xs)
        sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        sy = math.sqrt(sum((y - my) ** 2 for y in ys))
        r = (
            sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sx * sy)
            if sx and sy
            else 0
        )
        scores.append({"factor": key, "correlation": r, "effectMagnitude": abs(r)})
    scores.sort(key=lambda row: row["effectMagnitude"], reverse=True)
    return result(
        summary={
            "factorCount": len(scores),
            "dominantFactor": scores[0]["factor"] if scores else "",
        },
        tables=[
            table(
                "Risk factor sensitivity",
                [
                    ("factor", "Factor"),
                    ("correlation", "Correlation"),
                    ("effectMagnitude", "Absolute correlation"),
                ],
                scores,
            )
        ],
        notes=[
            "Ranks linear association in the supplied data; interaction and causal effects require a separate model."
        ],
    )


@feature(
    "studiesRisk.tornadoChart",
    "Tornado Chart",
    part="settings",
    fields=[
        text(
            "ranges",
            "Low and high outcome by factor",
            '[{"factor":"Steel price","low":950000,"high":1100000},{"factor":"Delay","low":900000,"high":1250000}]',
        )
    ],
    requires_project=False,
)
def tornado_chart(ctx: FeatureContext, values: dict) -> dict:
    """Rank factor influence ranges by the width of their low-to-high outcome span."""
    rows = records(values["ranges"], "tornado ranges")
    output = []
    for row in rows:
        try:
            low, high = float(row["low"]), float(row["high"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError("Every factor needs numeric low and high outcomes.") from error
        output.append(
            {
                "factor": row.get("factor", "Factor"),
                "low": low,
                "high": high,
                "swing": abs(high - low),
            }
        )
    output.sort(key=lambda row: row["swing"], reverse=True)
    return result(
        summary={"factorCount": len(output), "largestSwing": output[0]["swing"] if output else 0},
        tables=[
            table(
                "Tornado chart ranges",
                [
                    ("factor", "Factor"),
                    ("low", "Low outcome"),
                    ("high", "High outcome"),
                    ("swing", "Range swing"),
                ],
                output,
            )
        ],
        notes=[
            "Rows are ordered by absolute low-to-high outcome span; each scenario's units should be consistent."
        ],
    )


@feature(
    "studiesRisk.confidenceLevel",
    "Confidence Level",
    part="settings",
    fields=[
        number("mean", "Sample mean", 100, unit="kN"),
        number("standardDeviation", "Sample standard deviation", 12, unit="kN", min=0),
        number("sampleCount", "Independent samples", 40, min=2),
        number("confidence", "Confidence level", 0.95, min=0.5, max=0.999),
    ],
    requires_project=False,
)
def confidence_level(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a two-sided normal-approximation confidence interval for a sample mean."""
    z = _normal_quantile((1 + values["confidence"]) / 2)
    half = z * values["standardDeviation"] / math.sqrt(values["sampleCount"])
    return result(
        summary={
            "confidence": values["confidence"],
            "lowerBound": values["mean"] - half,
            "upperBound": values["mean"] + half,
            "halfWidth": half,
        },
        notes=[
            "Uses a standard-normal critical value for independent observations; small-sample t correction and distributional uncertainty are not applied."
        ],
    )


@feature(
    "studiesRisk.riskReport",
    "Risk Report",
    part="settings",
    fields=[
        text(
            "risks",
            "Scored risk register",
            '[{"id":"R1","probability":0.2,"impact":100000},{"id":"R2","probability":0.05,"impact":500000}]',
        )
    ],
    requires_project=False,
)
def risk_report(ctx: FeatureContext, values: dict) -> dict:
    """Summarize expected losses and rank the supplied risk register for reporting."""
    output = []
    for row in records(values["risks"], "risk report rows"):
        try:
            probability, impact = float(row["probability"]), float(row["impact"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each risk needs numeric probability and impact fields."
            ) from error
        output.append(
            {
                "id": row.get("id", "Risk"),
                "expectedLoss": probability * impact,
                "probability": probability,
                "impact": impact,
            }
        )
    output.sort(key=lambda row: row["expectedLoss"], reverse=True)
    return result(
        summary={
            "riskCount": len(output),
            "portfolioExpectedLoss": sum(row["expectedLoss"] for row in output),
            "highestRisk": output[0]["id"] if output else "",
        },
        tables=[
            table(
                "Ranked risks",
                [
                    ("rank", "Rank"),
                    ("id", "Risk"),
                    ("probability", "Probability"),
                    ("impact", "Impact"),
                    ("expectedLoss", "Expected loss"),
                ],
                [dict(row, rank=i + 1) for i, row in enumerate(output)],
            )
        ],
        notes=[
            "Expected-loss ranking is a screening measure; it does not replace severity-based or safety risk evaluation."
        ],
    )


@feature(
    "studiesRisk.responseAction",
    "Response Action",
    part="settings",
    fields=[
        select(
            "strategy",
            "Response strategy",
            [
                ("avoid", "Avoid"),
                ("reduce", "Reduce likelihood"),
                ("transfer", "Transfer consequence"),
                ("accept", "Accept"),
            ],
            "reduce",
        ),
        number("probability", "Current probability", 0.2, min=0, max=1),
        number("impact", "Current consequence", 100000, unit="currency", min=0),
        number("effectiveness", "Action effectiveness", 0.5, min=0, max=1),
    ],
    requires_project=False,
)
def response_action(ctx: FeatureContext, values: dict) -> dict:
    """Estimate how an avoidance, reduction, transfer or acceptance action changes expected loss."""
    p, impact, e = values["probability"], values["impact"], values["effectiveness"]
    new_p, new_impact = (
        (0.0, impact)
        if values["strategy"] == "avoid"
        else (p * (1 - e), impact)
        if values["strategy"] == "reduce"
        else (p, impact * (1 - e))
        if values["strategy"] == "transfer"
        else (p, impact)
    )
    return result(
        summary={
            "strategy": values["strategy"],
            "initialExpectedLoss": p * impact,
            "residualExpectedLoss": new_p * new_impact,
            "expectedLossReduction": p * impact - new_p * new_impact,
        },
        notes=[
            "Effectiveness is a scenario assumption. Transfer reduces the retained consequence only and does not remove the underlying hazard."
        ],
    )


@feature(
    "studiesRisk.mitigationCost",
    "Mitigation Cost",
    part="settings",
    fields=[
        number("mitigationCost", "Mitigation cost", 25000, unit="currency", min=0),
        number("lossBefore", "Expected loss before", 80000, unit="currency", min=0),
        number("lossAfter", "Expected loss after", 30000, unit="currency", min=0),
        number("life", "Benefit period", 5, unit="year", min=1, max=100),
        number("discountRate", "Discount rate", 0.04, min=0, max=1),
    ],
    requires_project=False,
)
def mitigation_cost(ctx: FeatureContext, values: dict) -> dict:
    """Compare mitigation cost with the discounted expected-loss reduction over its service life."""
    saving = values["lossBefore"] - values["lossAfter"]
    rate, life = values["discountRate"], int(values["life"])
    pv = saving * life if rate == 0 else saving * (1 - (1 + rate) ** -life) / rate
    return result(
        summary={
            "annualExpectedLossReduction": saving,
            "presentValueBenefit": pv,
            "mitigationCost": values["mitigationCost"],
            "netPresentValue": pv - values["mitigationCost"],
            "benefitCostRatio": pv / values["mitigationCost"] if values["mitigationCost"] else None,
        },
        notes=[
            "Expected-loss reductions are treated as level annual benefits at year-end; non-financial safety and resilience benefits are not monetized."
        ],
    )


@feature(
    "studiesRisk.residualRisk",
    "Residual Risk",
    part="settings",
    fields=[
        number("initialProbability", "Initial probability", 0.2, min=0, max=1),
        number("initialImpact", "Initial impact", 100, min=0),
        number("probabilityReduction", "Probability reduction fraction", 0.5, min=0, max=1),
        number("impactReduction", "Impact reduction fraction", 0.25, min=0, max=1),
    ],
    requires_project=False,
)
def residual_risk(ctx: FeatureContext, values: dict) -> dict:
    """Calculate initial and post-mitigation expected risk score from likelihood and consequence reductions."""
    initial = values["initialProbability"] * values["initialImpact"]
    p2 = values["initialProbability"] * (1 - values["probabilityReduction"])
    i2 = values["initialImpact"] * (1 - values["impactReduction"])
    return result(
        summary={
            "initialScore": initial,
            "residualProbability": p2,
            "residualImpact": i2,
            "residualScore": p2 * i2,
            "scoreReduction": initial - p2 * i2,
        },
        notes=[
            "Probability and consequence reduction factors are independent user assumptions and are multiplied to estimate residual risk."
        ],
    )


@feature(
    "studiesRisk.actionOwner",
    "Action Owner",
    part="settings",
    fields=[
        text(
            "actions",
            "Risk actions",
            '[{"id":"A-01","action":"Add inspection hold point","owner":"Site engineer","due":"2026-12-15","status":"open"}]',
        )
    ],
    requires_project=False,
)
def action_owner(ctx: FeatureContext, values: dict) -> dict:
    """Validate and tabulate accountable owners and due dates for risk response actions."""
    rows = records(values["actions"], "risk actions")
    missing = [row.get("id", "Action") for row in rows if not str(row.get("owner", "")).strip()]
    output = [
        {
            "id": row.get("id", "Action"),
            "action": row.get("action", ""),
            "owner": row.get("owner", "Unassigned"),
            "due": row.get("due", ""),
            "status": row.get("status", "open"),
        }
        for row in rows
    ]
    return result(
        summary={
            "actionCount": len(output),
            "unassignedCount": len(missing),
            "owners": len({row["owner"] for row in output if row["owner"] != "Unassigned"}),
        },
        tables=[
            table(
                "Action ownership",
                [
                    ("id", "Action id"),
                    ("action", "Action"),
                    ("owner", "Owner"),
                    ("due", "Due date"),
                    ("status", "Status"),
                ],
                output,
            )
        ],
        notes=[
            "Assignment is recorded as supplied; due-date parsing and workflow notifications are not performed."
        ],
    )


@feature(
    "studiesRisk.progressiveCollapse",
    "Progressive Collapse",
    part="settings",
    fields=[
        number("lostColumnLoad", "Load on removed column", 900, unit="kN", min=0),
        number("alternatePathCapacity", "Alternate-path capacity", 1300, unit="kN", min=0),
        number("dynamicIncrease", "Dynamic response multiplier", 1.5, min=1, max=5),
        number("redistributionFactor", "Redistributed share", 1, min=0, max=2),
    ],
    requires_project=False,
)
def progressive_collapse(ctx: FeatureContext, values: dict) -> dict:
    """Screen alternate-path demand following support loss with explicit redistribution and dynamic factors."""
    demand = values["lostColumnLoad"] * values["redistributionFactor"] * values["dynamicIncrease"]
    reserve = values["alternatePathCapacity"] - demand
    return result(
        summary={
            "amplifiedDemandKn": demand,
            "alternatePathCapacityKn": values["alternatePathCapacity"],
            "reserveKn": reserve,
            "capacityDemandRatio": values["alternatePathCapacity"] / demand if demand else math.inf,
            "passesScreen": reserve >= 0,
        },
        notes=[
            "Static alternate-path comparison using user-selected redistribution and dynamic factors; it is not a full nonlinear removal analysis."
        ],
    )


@feature(
    "studiesRisk.explosionLoad",
    "Explosion Load",
    part="settings",
    fields=[
        number("peakPressure", "Peak reflected pressure", 40, unit="kPa", min=0),
        number("duration", "Positive phase duration", 0.08, unit="s", min=0),
        number("panelArea", "Loaded panel area", 12, unit="m²", min=0),
        number("mass", "Effective mass", 8000, unit="kg", min=1),
    ],
    requires_project=False,
)
def explosion_load(ctx: FeatureContext, values: dict) -> dict:
    """Convert a supplied triangular reflected pressure pulse into panel impulse and velocity change."""
    impulse = values["peakPressure"] * 1000 * values["duration"] / 2
    total_impulse = impulse * values["panelArea"]
    return result(
        summary={
            "peakForceKn": values["peakPressure"] * values["panelArea"],
            "impulsePaS": impulse,
            "panelImpulseNs": total_impulse,
            "rigidBodyVelocityChangeMPerS": total_impulse / values["mass"],
        },
        notes=[
            "The positive phase is idealized as a triangular pulse at uniform reflected pressure; spatial pressure variation and blast wave prediction are excluded."
        ],
    )


@feature(
    "studiesRisk.fireExposure",
    "Fire Exposure",
    part="settings",
    fields=[
        number("exposureMinutes", "Exposure time", 60, unit="min", min=0),
        number("initialTemperature", "Initial temperature", 20, unit="°C"),
        number("targetTemperature", "Material target temperature", 500, unit="°C", min=0),
    ],
    requires_project=False,
)
def fire_exposure(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate gas temperature under a nominal logarithmic compartment fire curve and compare a target."""
    t = values["exposureMinutes"]
    gas = values["initialTemperature"] + 345 * math.log10(8 * t + 1)
    return result(
        summary={
            "gasTemperatureC": gas,
            "targetTemperatureC": values["targetTemperature"],
            "temperatureDifferenceC": gas - values["targetTemperature"],
        },
        tables=[
            table(
                "Exposure time points",
                [("minutes", "Exposure", "min"), ("gasTemperature", "Gas temperature", "°C")],
                [
                    {
                        "minutes": minute,
                        "gasTemperature": values["initialTemperature"]
                        + 345 * math.log10(8 * minute + 1),
                    }
                    for minute in (0, t / 4, t / 2, 3 * t / 4, t)
                ],
            )
        ],
        notes=[
            "Nominal logarithmic gas-temperature curve; member temperature depends on section factor, protection, thermal properties and ventilation and is not inferred here."
        ],
    )


@feature(
    "studiesRisk.vehicleImpact",
    "Vehicle Impact",
    part="settings",
    fields=[
        number("vehicleMass", "Vehicle mass", 2500, unit="kg", min=1),
        number("speed", "Impact speed", 15, unit="m/s", min=0),
        number("crushDistance", "Stopping distance", 0.4, unit="m", min=0.001),
        number("impactAngle", "Angle to barrier normal", 0, unit="°", min=0, max=90),
    ],
    requires_project=False,
)
def vehicle_impact(ctx: FeatureContext, values: dict) -> dict:
    """Estimate normal impact energy and average stopping force from vehicle mass and crush distance."""
    normal_speed = values["speed"] * math.cos(math.radians(values["impactAngle"]))
    energy = 0.5 * values["vehicleMass"] * normal_speed**2
    force = energy / values["crushDistance"]
    return result(
        summary={
            "normalImpactSpeedMPerS": normal_speed,
            "normalKineticEnergyKj": energy / 1000,
            "averageStoppingForceKn": force / 1000,
        },
        notes=[
            "Rigid-mass kinetic energy divided by the specified stopping distance gives average force; peak force, braking and barrier interaction are not calculated."
        ],
    )


@feature(
    "studiesRisk.betaIndex",
    "Beta Index",
    part="settings",
    fields=[
        number("meanResistance", "Mean resistance", 500, unit="kN"),
        number("meanLoad", "Mean load effect", 350, unit="kN"),
        number("stdResistance", "Resistance standard deviation", 50, unit="kN", min=0),
        number("stdLoad", "Load standard deviation", 40, unit="kN", min=0),
        number("correlation", "Resistance-load correlation", 0, min=-1, max=1),
    ],
    requires_project=False,
)
def beta_index(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a first-order reliability index including a supplied resistance-load correlation."""
    variance = (
        values["stdResistance"] ** 2
        + values["stdLoad"] ** 2
        - 2 * values["correlation"] * values["stdResistance"] * values["stdLoad"]
    )
    if variance <= 0:
        raise FeatureInputError("The combined limit-state variance must be positive.")
    beta = (values["meanResistance"] - values["meanLoad"]) / math.sqrt(variance)
    pf = 0.5 * math.erfc(beta / math.sqrt(2))
    return result(
        summary={"beta": beta, "failureProbability": pf, "limitStateStd": math.sqrt(variance)},
        notes=[
            "Linear resistance-minus-load limit state with normal marginals and specified correlation; higher-order and non-normal effects are not represented."
        ],
    )


@feature(
    "studiesRisk.failureProbability",
    "Failure Probability",
    part="settings",
    fields=[
        number("capacityMean", "Capacity mean", 500, unit="kN"),
        number("capacityStd", "Capacity standard deviation", 40, unit="kN", min=0),
        number("demand", "Deterministic demand", 420, unit="kN"),
    ],
    requires_project=False,
)
def failure_probability(ctx: FeatureContext, values: dict) -> dict:
    """Estimate failure probability for normally distributed capacity under fixed demand."""
    if values["capacityStd"] == 0:
        pf = float(values["capacityMean"] < values["demand"])
    else:
        z = (values["demand"] - values["capacityMean"]) / values["capacityStd"]
        pf = 0.5 * math.erfc(-z / math.sqrt(2))
    return result(
        summary={
            "failureProbability": pf,
            "reliabilityIndex": _normal_quantile(1 - pf)
            if 0 < pf < 1
            else math.inf
            if pf == 0
            else -math.inf,
        },
        notes=[
            "Normal capacity distribution and deterministic demand; model uncertainty and demand variability are excluded."
        ],
    )


@feature(
    "studiesRisk.limitStateFunction",
    "Limit State Function",
    part="settings",
    fields=[
        text(
            "terms",
            "Limit-state terms",
            '[{"name":"capacity","value":500,"sign":1},{"name":"demand","value":420,"sign":-1},{"name":"wind","value":35,"sign":-1}]',
        )
    ],
    requires_project=False,
)
def limit_state_function(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate an explicit linear limit-state function as the signed sum of declared terms."""
    rows, total = [], 0.0
    for item in records(values["terms"], "limit-state terms"):
        try:
            value, sign = float(item["value"]), float(item.get("sign", 1))
        except (TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each limit-state term needs numeric value and sign fields."
            ) from error
        contribution = value * sign
        total += contribution
        rows.append(
            {
                "term": item.get("name", "Term"),
                "value": value,
                "sign": sign,
                "contribution": contribution,
            }
        )
    return result(
        summary={
            "limitStateValue": total,
            "safeBySignConvention": total >= 0,
            "termCount": len(rows),
        },
        tables=[
            table(
                "Limit-state terms",
                [
                    ("term", "Term"),
                    ("value", "Value"),
                    ("sign", "Sign"),
                    ("contribution", "Contribution"),
                ],
                rows,
            )
        ],
        notes=["Positive limit-state values are safe under the user-declared sign convention."],
    )


@feature(
    "studiesRisk.reliabilityMap",
    "Reliability Map",
    part="settings",
    fields=[
        text(
            "locations",
            "Site locations with beta values",
            '[{"id":"P1","x":0,"y":0,"beta":3.2},{"id":"P2","x":100,"y":0,"beta":2.5}]',
        )
    ],
    requires_project=False,
)
def reliability_map(ctx: FeatureContext, values: dict) -> dict:
    """Convert reliability indices to normal-tail probabilities at supplied site coordinates."""
    output = []
    for item in records(values["locations"], "reliability locations"):
        try:
            beta, x, y = float(item["beta"]), float(item["x"]), float(item["y"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError("Each location needs numeric x, y and beta fields.") from error
        output.append(
            {
                "id": item.get("id", "Point"),
                "x": x,
                "y": y,
                "beta": beta,
                "failureProbability": 0.5 * math.erfc(beta / math.sqrt(2)),
            }
        )
    return result(
        summary={
            "locationCount": len(output),
            "maximumFailureProbability": max(row["failureProbability"] for row in output),
        },
        tables=[
            table(
                "Reliability map points",
                [
                    ("id", "Point"),
                    ("x", "X"),
                    ("y", "Y"),
                    ("beta", "Reliability index"),
                    ("failureProbability", "Failure probability"),
                ],
                output,
            )
        ],
        notes=[
            "Probabilities are obtained from the standard-normal tail associated with each supplied beta index."
        ],
    )
