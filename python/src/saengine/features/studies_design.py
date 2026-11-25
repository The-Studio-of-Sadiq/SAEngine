"""Studies Design - option studies, objective setup, optimizers and comparisons."""

from __future__ import annotations

import math
import random

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.studies_common import (
    records,
    study_path,
    write_json,
)


def _weighted(row: dict, weights: dict[str, float]) -> float:
    """Weighted mean of normalized numeric criteria on one candidate."""
    terms = [(float(row[key]), weight) for key, weight in weights.items() if key in row]
    if not terms or sum(abs(weight) for _, weight in terms) == 0:
        raise FeatureInputError("Candidates need numeric values for the weighted objectives.")
    return sum(value * weight for value, weight in terms) / sum(abs(weight) for _, weight in terms)


@feature(
    "studiesDesign.studySetup",
    "Study Setup",
    part="settings",
    fields=[
        text("title", "Study title", "Frame options"),
        text("variables", "Variables JSON", '[{"name":"spanM","min":5,"max":8,"unit":"m"}]'),
        text("objectives", "Objective names", "cost,carbon,deflection"),
    ],
    requires_project=False,
)
def study_setup(ctx: FeatureContext, values: dict) -> dict:
    """Validate a study's variable and objective declarations and save a readable study record."""
    variables = records(values["variables"], "design variables")
    names = [str(item.get("name", "")).strip() for item in variables]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise FeatureInputError("Each design variable needs a unique non-empty name.")
    objectives = [part.strip() for part in values["objectives"].split(",") if part.strip()]
    if not objectives:
        raise FeatureInputError("Enter at least one objective.")
    payload = {"title": values["title"].strip(), "variables": variables, "objectives": objectives}
    path = write_json(ctx, study_path("study-setup"), payload)
    return result(
        summary={
            "title": payload["title"],
            "variableCount": len(names),
            "objectiveCount": len(objectives),
            "outputPath": path,
        },
        tables=[
            table(
                "Study variables",
                [("name", "Variable"), ("min", "Minimum"), ("max", "Maximum"), ("unit", "Unit")],
                variables,
            )
        ],
        notes=[f"Validated study definition saved to {path}."],
    )


@feature(
    "studiesDesign.variables",
    "Variables",
    part="settings",
    fields=[
        text(
            "variables",
            "Variable definitions",
            '[{"name":"spanM","min":5,"max":8,"unit":"m"},{"name":"depthMm","min":400,"max":700,"unit":"mm"}]',
        )
    ],
    requires_project=False,
)
def variables(ctx: FeatureContext, values: dict) -> dict:
    """Check that each study variable has an ordered finite range and report its range width."""
    rows = records(values["variables"], "variables")
    output = []
    for item in rows:
        try:
            low, high = float(item["min"]), float(item["max"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError("Each variable needs numeric min and max values.") from error
        if not math.isfinite(low + high) or high <= low:
            raise FeatureInputError("Variable limits must be finite and max must exceed min.")
        output.append(
            {
                "name": str(item.get("name", "Variable")),
                "min": low,
                "max": high,
                "range": high - low,
                "unit": item.get("unit", ""),
            }
        )
    return result(
        summary={
            "variableCount": len(output),
            "totalRangeWidth": sum(row["range"] for row in output),
        },
        tables=[
            table(
                "Variable ranges",
                [
                    ("name", "Variable"),
                    ("min", "Minimum"),
                    ("max", "Maximum"),
                    ("range", "Range"),
                    ("unit", "Unit"),
                ],
                output,
            )
        ],
        notes=[
            "Ranges are reported in each variable's stated unit; variables are not changed by this check."
        ],
    )


@feature(
    "studiesDesign.objectives",
    "Objectives",
    part="settings",
    fields=[
        text(
            "objectives",
            "Objective weights JSON",
            '[{"name":"cost","weight":0.5,"direction":"min"},{"name":"carbon","weight":0.3,"direction":"min"},{"name":"performance","weight":0.2,"direction":"max"}]',
        )
    ],
    requires_project=False,
)
def objectives(ctx: FeatureContext, values: dict) -> dict:
    """Normalize non-negative objective weights and retain each objective direction."""
    rows = records(values["objectives"], "objectives")
    try:
        weights = [float(row["weight"]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise FeatureInputError("Each objective needs a numeric weight.") from error
    if any(weight < 0 for weight in weights) or sum(weights) <= 0:
        raise FeatureInputError(
            "Objective weights must be non-negative and at least one must be positive."
        )
    if any(row.get("direction", "min") not in ("min", "max") for row in rows):
        raise FeatureInputError("Objective direction must be min or max.")
    normalized = [
        {
            "name": row.get("name", f"Objective {i + 1}"),
            "weight": weight / sum(weights),
            "direction": row.get("direction", "min"),
        }
        for i, (row, weight) in enumerate(zip(rows, weights, strict=True))
    ]
    return result(
        summary={"objectiveCount": len(rows), "weightSum": 1.0},
        tables=[
            table(
                "Normalized objectives",
                [
                    ("name", "Objective"),
                    ("weight", "Normalized weight"),
                    ("direction", "Direction"),
                ],
                normalized,
            )
        ],
        notes=[
            "Weights are normalized to sum to one; criteria values need a consistent normalization before aggregation."
        ],
    )


@feature(
    "studiesDesign.constraints",
    "Constraints",
    part="settings",
    fields=[
        text(
            "constraints",
            "Constraint checks JSON",
            '[{"name":"drift","value":0.012,"limit":0.02,"direction":"max"},{"name":"cost","value":900000,"limit":1000000,"direction":"max"}]',
        )
    ],
    requires_project=False,
)
def constraints(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate numeric upper or lower bounds for a set of declared study constraints."""
    rows = records(values["constraints"], "constraints")
    output = []
    for item in rows:
        try:
            value, limit = float(item["value"]), float(item["limit"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each constraint needs numeric value and limit fields."
            ) from error
        direction = item.get("direction", "max")
        if direction not in ("max", "min"):
            raise FeatureInputError("Constraint direction must be max or min.")
        output.append(
            {
                "name": item.get("name", "Constraint"),
                "value": value,
                "limit": limit,
                "direction": direction,
                "margin": limit - value if direction == "max" else value - limit,
                "passes": value <= limit if direction == "max" else value >= limit,
            }
        )
    return result(
        summary={
            "constraintCount": len(output),
            "satisfiedCount": sum(row["passes"] for row in output),
            "feasible": all(row["passes"] for row in output),
        },
        tables=[
            table(
                "Constraint results",
                [
                    ("name", "Constraint"),
                    ("value", "Value"),
                    ("limit", "Limit"),
                    ("margin", "Margin"),
                    ("passes", "Passes"),
                ],
                output,
            )
        ],
        notes=["Positive margin denotes compliance with the stated bound."],
    )


@feature(
    "studiesDesign.designSpace",
    "Design Space",
    part="settings",
    fields=[
        text(
            "bounds",
            "Continuous variable bounds",
            '[{"name":"spanM","min":5,"max":8},{"name":"depthMm","min":400,"max":700}]',
        )
    ],
    requires_project=False,
)
def design_space(ctx: FeatureContext, values: dict) -> dict:
    """Compute the dimensionality and hyper-rectangle volume of a continuous design space."""
    rows = records(values["bounds"], "design space bounds")
    volume, output = 1.0, []
    for row in rows:
        try:
            low, high = float(row["min"]), float(row["max"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Every design variable needs numeric min and max bounds."
            ) from error
        if not high > low:
            raise FeatureInputError("Every design-space maximum must exceed its minimum.")
        width = high - low
        volume *= width
        output.append(
            {"name": row.get("name", "Variable"), "minimum": low, "maximum": high, "width": width}
        )
    return result(
        summary={"dimensionCount": len(output), "hypervolume": volume},
        tables=[
            table(
                "Continuous design bounds",
                [
                    ("name", "Variable"),
                    ("minimum", "Minimum"),
                    ("maximum", "Maximum"),
                    ("width", "Width"),
                ],
                output,
            )
        ],
        notes=[
            "Hypervolume is the product of widths; mixed units make its magnitude useful only as a design-space descriptor."
        ],
    )


@feature(
    "studiesDesign.parameterRange",
    "Parameter Range",
    part="settings",
    fields=[
        text("parameter", "Parameter", "columnDepthMm"),
        number("minimum", "Minimum", 400),
        number("maximum", "Maximum", 700),
        number("increment", "Increment", 50),
    ],
)
def parameter_range(ctx: FeatureContext, values: dict) -> dict:
    """Build a discrete design-variable range using a fixed increment."""
    low, high, step = values["minimum"], values["maximum"], values["increment"]
    if step <= 0 or high < low:
        raise FeatureInputError("Use a positive increment and a maximum at or above the minimum.")
    count = math.floor((high - low) / step + 1e-10) + 1
    if count > 500:
        raise FeatureInputError("A discrete parameter range may contain at most 500 values.")
    vals = [low + i * step for i in range(count)]
    return result(
        summary={
            "parameter": values["parameter"],
            "valueCount": len(vals),
            "maximumGenerated": vals[-1],
        },
        tables=[
            table(
                "Discrete parameter values",
                [("index", "Index"), ("value", values["parameter"])],
                [{"index": i + 1, "value": value} for i, value in enumerate(vals)],
            )
        ],
        notes=["The exact maximum is present only when it lies on the increment sequence."],
    )


@feature(
    "studiesDesign.runStudy",
    "Run Study",
    part="settings",
    fields=[
        text(
            "candidates",
            "Candidate result records",
            '[{"name":"A","cost":100,"carbon":80,"deflection":4},{"name":"B","cost":110,"carbon":60,"deflection":3}]',
        ),
        text("weights", "Objective weights JSON", '{"cost":0.5,"carbon":0.3,"deflection":0.2}'),
    ],
    requires_project=False,
)
def run_study(ctx: FeatureContext, values: dict) -> dict:
    """Score a finite set of candidates using transparent weighted normalized criteria."""
    candidates, weights = (
        records(values["candidates"], "study candidates"),
        __import__("json").loads(values["weights"]),
    )
    if not isinstance(weights, dict) or not weights:
        raise FeatureInputError(
            "Objective weights must be a JSON object of criterion names and weights."
        )
    metric_rows = []
    for candidate in candidates:
        try:
            score = _weighted(candidate, {key: float(weight) for key, weight in weights.items()})
        except (TypeError, ValueError) as error:
            raise FeatureInputError("Objective weights must be numeric.") from error
        metric_rows.append({"name": str(candidate.get("name", "Candidate")), "score": score})
    metric_rows.sort(key=lambda item: item["score"])
    return result(
        summary={"candidateCount": len(metric_rows), "lowestWeightedScore": metric_rows[0]["name"]},
        tables=[
            table(
                "Study scores",
                [("rank", "Rank"), ("name", "Candidate"), ("score", "Weighted score")],
                [dict(row, rank=i + 1) for i, row in enumerate(metric_rows)],
            )
        ],
        notes=[
            "Inputs are combined as supplied; normalize mixed engineering units and set direction before using the score to choose a design."
        ],
    )


@feature(
    "studiesDesign.batchRuns",
    "Batch Runs",
    part="settings",
    fields=[
        text(
            "runs",
            "Study run specifications",
            '[{"study":"Grid A","variants":20,"secondsEach":5},{"study":"Grid B","variants":12,"secondsEach":7}]',
        )
    ],
    requires_project=False,
)
def batch_runs(ctx: FeatureContext, values: dict) -> dict:
    """Estimate queued solver time from declared variant counts and measured per-run durations."""
    rows = records(values["runs"], "batch runs")
    output = []
    for row in rows:
        try:
            count, seconds = int(row["variants"]), float(row["secondsEach"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each batch run needs integer variants and numeric secondsEach."
            ) from error
        if count < 0 or seconds < 0:
            raise FeatureInputError("Variant counts and run durations must be non-negative.")
        output.append(
            {
                "study": row.get("study", "Study"),
                "variants": count,
                "secondsEach": seconds,
                "estimatedSeconds": count * seconds,
            }
        )
    return result(
        summary={
            "queuedStudies": len(output),
            "totalVariants": sum(r["variants"] for r in output),
            "estimatedSeconds": sum(r["estimatedSeconds"] for r in output),
        },
        tables=[
            table(
                "Batch estimates",
                [
                    ("study", "Study"),
                    ("variants", "Variants"),
                    ("secondsEach", "Seconds per variant", "s"),
                    ("estimatedSeconds", "Estimated time", "s"),
                ],
                output,
            )
        ],
        notes=[
            "This is a runtime estimate only; the feature engine does not create a background queue."
        ],
    )


@feature(
    "studiesDesign.sampler",
    "Sampler",
    part="settings",
    fields=[
        text(
            "variables",
            "Variable ranges JSON",
            '[{"name":"span","min":5,"max":8},{"name":"depth","min":400,"max":700}]',
        ),
        number("samples", "Sample count", 10, min=2, max=500),
        number("seed", "Seed", 17, min=0, max=2147483647),
        select(
            "method",
            "Sampling method",
            [("lhs", "Latin hypercube"), ("random", "Uniform random")],
            "lhs",
        ),
    ],
    requires_project=False,
)
def sampler(ctx: FeatureContext, values: dict) -> dict:
    """Sample declared continuous bounds using a repeatable Latin hypercube or uniform design."""
    variables = records(values["variables"], "variable ranges")
    rng, count = random.Random(int(values["seed"])), int(values["samples"])
    samples: list[dict] = [{"sample": i + 1} for i in range(count)]
    for var in variables:
        try:
            low, high = float(var["min"]), float(var["max"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each sampled variable needs numeric min and max values."
            ) from error
        if high <= low:
            raise FeatureInputError("Every sample range maximum must exceed its minimum.")
        if values["method"] == "lhs":
            strata = list(range(count))
            rng.shuffle(strata)
            levels = [(index + rng.random()) / count for index in strata]
        else:
            levels = [rng.random() for _ in range(count)]
        for row, level in zip(samples, levels, strict=True):
            row[str(var.get("name", "x"))] = low + level * (high - low)
    return result(
        summary={"sampleCount": count, "variableCount": len(variables), "method": values["method"]},
        tables=[table("Design samples", [(key, key.title()) for key in samples[0]], samples)],
        notes=[
            "Latin hypercube stratifies each variable independently; correlations between variables are not imposed."
        ],
    )


@feature(
    "studiesDesign.tradeOffChart",
    "Trade-Off Chart",
    part="settings",
    fields=[
        text(
            "options",
            "Options JSON",
            '[{"name":"A","cost":100,"carbon":80},{"name":"B","cost":110,"carbon":60}]',
        ),
        text("x", "Horizontal objective", "cost"),
        text("y", "Vertical objective", "carbon"),
    ],
    requires_project=False,
)
def trade_off_chart(ctx: FeatureContext, values: dict) -> dict:
    """Produce plotted coordinate rows for a two-objective trade-off chart."""
    options = records(values["options"], "chart options")
    output = []
    for item in options:
        try:
            x, y = float(item[values["x"]]), float(item[values["y"]])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Every option needs numeric values for both chart axes."
            ) from error
        output.append({"option": item.get("name", "Option"), "x": x, "y": y})
    return result(
        summary={"pointCount": len(output), "xObjective": values["x"], "yObjective": values["y"]},
        tables=[
            table(
                "Trade-off points",
                [("option", "Option"), ("x", values["x"]), ("y", values["y"])],
                output,
            )
        ],
        notes=[
            "Each row supplies a chart coordinate; scales and objective directions are the user's responsibility."
        ],
    )


@feature(
    "studiesDesign.paretoFront",
    "Pareto Front",
    part="settings",
    fields=[
        text(
            "options",
            "Options JSON",
            '[{"name":"A","cost":100,"carbon":80},{"name":"B","cost":110,"carbon":60},{"name":"C","cost":120,"carbon":90}]',
        ),
        text("objectives", "Minimized objectives", "cost,carbon"),
    ],
    requires_project=False,
)
def pareto_front(ctx: FeatureContext, values: dict) -> dict:
    """Identify non-dominated options when all listed objectives are minimized."""
    options, objectives = (
        records(values["options"], "Pareto options"),
        [p.strip() for p in values["objectives"].split(",") if p.strip()],
    )
    if not objectives:
        raise FeatureInputError("List at least one minimized objective.")
    converted = []
    for item in options:
        try:
            converted.append((item, tuple(float(item[key]) for key in objectives)))
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Every candidate needs a numeric value for each objective."
            ) from error
    front = []
    for candidate, scores in converted:
        dominated = any(
            other != candidate
            and all(a <= b for a, b in zip(other_scores, scores, strict=True))
            and any(a < b for a, b in zip(other_scores, scores, strict=True))
            for other, other_scores in converted
        )
        if not dominated:
            front.append(
                {
                    "name": candidate.get("name", "Option"),
                    **dict(zip(objectives, scores, strict=True)),
                }
            )
    return result(
        summary={"candidateCount": len(options), "paretoCount": len(front)},
        tables=[
            table(
                "Non-dominated options",
                [("name", "Option"), *[(key, key.title()) for key in objectives]],
                front,
            )
        ],
        notes=[
            "All objectives are treated as minimization criteria; equal objective vectors are retained."
        ],
    )


@feature(
    "studiesDesign.sensitivity",
    "Sensitivity",
    part="settings",
    fields=[
        text(
            "observations",
            "Input and result observations",
            '[{"span":5,"cost":100},{"span":6,"cost":115},{"span":7,"cost":130}]',
        ),
        text("output", "Output field", "cost"),
    ],
    requires_project=False,
)
def sensitivity(ctx: FeatureContext, values: dict) -> dict:
    """Rank numeric input columns by absolute Pearson correlation with a selected response."""
    rows = records(values["observations"], "sensitivity observations")
    try:
        y = [float(row[values["output"]]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise FeatureInputError(
            "Every observation needs the selected numeric output field."
        ) from error
    mean_y = sum(y) / len(y)
    denom_y = math.sqrt(sum((v - mean_y) ** 2 for v in y))
    scores = []
    for key in rows[0]:
        if key == values["output"]:
            continue
        try:
            xs = [float(row[key]) for row in rows]
        except (KeyError, TypeError, ValueError):
            continue
        mean_x = sum(xs) / len(xs)
        denom_x = math.sqrt(sum((v - mean_x) ** 2 for v in xs))
        correlation = (
            sum((x - mean_x) * (response - mean_y) for x, response in zip(xs, y, strict=True))
            / (denom_x * denom_y)
            if denom_x and denom_y
            else 0.0
        )
        scores.append(
            {"input": key, "correlation": correlation, "absoluteEffect": abs(correlation)}
        )
    scores.sort(key=lambda item: item["absoluteEffect"], reverse=True)
    return result(
        summary={
            "inputCount": len(scores),
            "topInput": scores[0]["input"] if scores else "",
            "output": values["output"],
        },
        tables=[
            table(
                "Correlation sensitivity",
                [
                    ("input", "Input"),
                    ("correlation", "Pearson r"),
                    ("absoluteEffect", "Absolute correlation"),
                ],
                scores,
            )
        ],
        notes=[
            "Absolute Pearson correlation ranks linear association in the supplied observations; it is not a causal or nonlinear sensitivity measure."
        ],
    )


@feature(
    "studiesDesign.exportStudy",
    "Export Study",
    part="settings",
    fields=[
        text(
            "results",
            "Study result rows",
            '[{"variant":"A","cost":100,"carbon":80},{"variant":"B","cost":110,"carbon":60}]',
        ),
        text("filename", "Workbook name", "study-results"),
    ],
)
def export_study(ctx: FeatureContext, values: dict) -> dict:
    """Write a workbook with one worksheet containing supplied study results."""
    rows = records(values["results"], "study results")
    if ctx.root is None:
        raise FeatureInputError("Open a project to write the study workbook.")
    safe = (
        "".join(ch for ch in values["filename"] if ch.isalnum() or ch in "-_ ")
        .strip()
        .replace(" ", "-")
        or "study-results"
    )
    target = ctx.root / "11 Exports" / f"{safe}.xlsx"
    try:
        from openpyxl import Workbook
    except ImportError as error:
        raise FeatureInputError(
            "The workbook writer dependency is unavailable in this environment."
        ) from error
    columns = list(dict.fromkeys(key for row in rows for key in row))
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Study Results"
    sheet.append(columns)
    for row in rows:
        sheet.append([row.get(key) for key in columns])
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)
    relative = target.relative_to(ctx.root).as_posix()
    return result(
        summary={"rowCount": len(rows), "columnCount": len(columns), "workbookPath": relative},
        notes=[f"Study results written to {relative}."],
    )


@feature(
    "studiesDesign.compareSchemes",
    "Compare Schemes",
    part="settings",
    fields=[
        text(
            "schemes",
            "Scheme records",
            '[{"name":"Steel","cost":1000,"carbon":800,"weight":50},{"name":"Concrete","cost":900,"carbon":900,"weight":70}]',
        ),
        text("metrics", "Compared metrics", "cost,carbon,weight"),
    ],
    requires_project=False,
)
def compare_schemes(ctx: FeatureContext, values: dict) -> dict:
    """Compare scheme metrics and calculate relative change from the first scheme."""
    rows, metrics = (
        records(values["schemes"], "schemes"),
        [x.strip() for x in values["metrics"].split(",") if x.strip()],
    )
    if len(rows) < 2:
        raise FeatureInputError("Provide at least two schemes to compare.")
    base = rows[0]
    output = []
    for row in rows:
        item = {"scheme": row.get("name", "Scheme")}
        for key in metrics:
            try:
                item[key] = float(row[key])
                item[f"{key}DeltaPct"] = (
                    100 * (float(row[key]) - float(base[key])) / abs(float(base[key]))
                    if float(base[key])
                    else None
                )
            except (KeyError, TypeError, ValueError) as error:
                raise FeatureInputError(f"Every scheme needs numeric {key} values.") from error
        output.append(item)
    columns = (
        [("scheme", "Scheme")]
        + [(key, key.title()) for key in metrics]
        + [(f"{key}DeltaPct", f"{key.title()} delta", "%") for key in metrics]
    )
    return result(
        summary={"schemeCount": len(output), "baselineScheme": base.get("name", "Scheme")},
        tables=[table("Scheme comparison", columns, output)],
        notes=[
            "Percentage change is relative to the first listed scheme; a zero baseline is shown as blank."
        ],
    )


@feature(
    "studiesDesign.costDelta",
    "Cost Delta",
    part="settings",
    fields=[
        number("baselineCost", "Baseline cost", 1000000, unit="currency", min=0),
        number("optionCost", "Option cost", 950000, unit="currency", min=0),
    ],
)
def cost_delta(ctx: FeatureContext, values: dict) -> dict:
    """Calculate absolute and percentage cost changes from a baseline option."""
    delta = values["optionCost"] - values["baselineCost"]
    pct = 100 * delta / values["baselineCost"] if values["baselineCost"] else None
    return result(
        summary={"deltaCurrency": delta, "deltaPercent": pct, "savingCurrency": -delta},
        notes=["A negative delta is a saving relative to the supplied baseline cost."],
    )


@feature(
    "studiesDesign.carbonDelta",
    "Carbon Delta",
    part="settings",
    fields=[
        number("baselineCarbon", "Baseline embodied carbon", 500000, unit="kg CO2e", min=0),
        number("optionCarbon", "Option embodied carbon", 420000, unit="kg CO2e", min=0),
    ],
)
def carbon_delta(ctx: FeatureContext, values: dict) -> dict:
    """Calculate absolute and percentage embodied-carbon changes from the baseline."""
    delta = values["optionCarbon"] - values["baselineCarbon"]
    pct = 100 * delta / values["baselineCarbon"] if values["baselineCarbon"] else None
    return result(
        summary={"deltaKgCo2e": delta, "deltaPercent": pct, "reductionKgCo2e": -delta},
        notes=[
            "The comparison uses the two user-supplied embodied-carbon totals and matching scope."
        ],
    )


@feature(
    "studiesDesign.overlayOptions",
    "Overlay Options",
    part="bim",
    fields=[
        text(
            "first",
            "First option geometry",
            '[{"id":"B1","x1":0,"y1":0,"z1":0,"x2":5,"y2":0,"z2":0}]',
        ),
        text(
            "second",
            "Second option geometry",
            '[{"id":"B1","x1":0,"y1":0,"z1":0,"x2":6,"y2":0,"z2":0}]',
        ),
    ],
    requires_project=False,
)
def overlay_options(ctx: FeatureContext, values: dict) -> dict:
    """Return matched line geometry from two options in one coordinate table for overlay views."""
    first, second = (
        records(values["first"], "first option geometry"),
        records(values["second"], "second option geometry"),
    )
    before = {str(row.get("id")): row for row in first}
    after = {str(row.get("id")): row for row in second}
    rows = []
    for key in sorted(before.keys() | after.keys()):
        rows.append(
            {
                "id": key,
                "first": before.get(key),
                "second": after.get(key),
                "state": "shared"
                if key in before and key in after
                else "added"
                if key in after
                else "removed",
            }
        )
    return result(
        summary={
            "elementCount": len(rows),
            "sharedCount": sum(row["state"] == "shared" for row in rows),
        },
        tables=[
            table(
                "Option overlay geometry",
                [
                    ("id", "Element"),
                    ("state", "State"),
                    ("first", "First geometry"),
                    ("second", "Second geometry"),
                ],
                rows,
            )
        ],
        notes=[
            "Coordinate records are passed through for a downstream model viewer; matching uses element id."
        ],
    )


@feature(
    "studiesDesign.diffView",
    "Diff View",
    part="bim",
    fields=[
        text("before", "Before model JSON", '{"elements":[{"id":"B1","section":"200x400"}]}'),
        text("after", "After model JSON", '{"elements":[{"id":"B1","section":"250x450"}]}'),
    ],
    requires_project=False,
)
def diff_view(ctx: FeatureContext, values: dict) -> dict:
    """Compare element records by id and report added, removed and changed fields."""
    left, right = (
        __import__("json").loads(values["before"]),
        __import__("json").loads(values["after"]),
    )
    left_rows = left.get("elements", []) if isinstance(left, dict) else []
    right_rows = right.get("elements", []) if isinstance(right, dict) else []
    before = {str(row.get("id")): row for row in left_rows if isinstance(row, dict)}
    after = {str(row.get("id")): row for row in right_rows if isinstance(row, dict)}
    diffs = []
    for key in sorted(before.keys() | after.keys()):
        if key not in before:
            diffs.append({"id": key, "change": "added", "fields": "*"})
        elif key not in after:
            diffs.append({"id": key, "change": "removed", "fields": "*"})
        else:
            changed = [
                name
                for name in before[key].keys() | after[key].keys()
                if before[key].get(name) != after[key].get(name)
            ]
            if changed:
                diffs.append(
                    {"id": key, "change": "modified", "fields": ", ".join(sorted(changed))}
                )
    return result(
        summary={
            "changeCount": len(diffs),
            "added": sum(row["change"] == "added" for row in diffs),
            "removed": sum(row["change"] == "removed" for row in diffs),
        },
        tables=[
            table(
                "Model differences",
                [("id", "Element"), ("change", "Change"), ("fields", "Changed fields")],
                diffs,
            )
        ],
        notes=["Elements are matched by id and compared as JSON properties."],
    )


@feature(
    "studiesDesign.optionBrowser",
    "Option Browser",
    part="bim",
    fields=[
        text("search", "Element name filter", ""),
        checkbox("includeMembers", "Include structural members", True),
    ],
)
def option_browser(ctx: FeatureContext, values: dict) -> dict:
    """Browse the project's building-model elements by identifier, type, section and material."""
    data = ctx.raw("bim")
    if not isinstance(data, dict):
        raise FeatureInputError("Open a project with a BIM model to browse its option elements.")
    elements = data.get("elements", [])
    query = values["search"].strip().casefold()
    rows = []
    for item in elements:
        if not isinstance(item, dict) or (
            query and query not in str(item.get("id", "")).casefold()
        ):
            continue
        if not values["includeMembers"] and item.get("type") == "Member":
            continue
        rows.append(
            {
                "id": item.get("id"),
                "type": item.get("type"),
                "section": item.get("section"),
                "material": item.get("material"),
            }
        )
    return result(
        summary={"elementCount": len(rows), "matchedFilter": values["search"]},
        tables=[
            table(
                "Project elements",
                [
                    ("id", "Element"),
                    ("type", "Type"),
                    ("section", "Section"),
                    ("material", "Material"),
                ],
                rows,
            )
        ],
        notes=["This browser reads the project's BIM source file and does not modify it."],
    )


@feature(
    "studiesDesign.geneticAlgorithm",
    "Genetic Algorithm",
    part="settings",
    fields=[
        number("lower", "Variable lower bound", 0, min=0),
        number("upper", "Variable upper bound", 10, min=0),
        number("target", "Target value", 7.5),
        number("population", "Population size", 40, min=4, max=500),
        number("generations", "Generations", 50, min=1, max=500),
        number("seed", "Random seed", 41, min=0, max=2147483647),
    ],
)
def genetic_algorithm(ctx: FeatureContext, values: dict) -> dict:
    """Minimize squared distance from a target with a bounded one-variable genetic search."""
    low, high = values["lower"], values["upper"]
    if high <= low or not low <= values["target"] <= high:
        raise FeatureInputError(
            "The upper bound must exceed the lower bound and contain the target."
        )
    rng, count = random.Random(int(values["seed"])), int(values["population"])
    population = [rng.uniform(low, high) for _ in range(count)]
    history = []
    for generation in range(int(values["generations"])):
        population.sort(key=lambda x: (x - values["target"]) ** 2)
        history.append(
            {
                "generation": generation + 1,
                "best": population[0],
                "objective": (population[0] - values["target"]) ** 2,
            }
        )
        parents = population[: max(2, count // 4)]
        children = parents[:2]
        while len(children) < count:
            parent = rng.choice(parents)
            child = min(high, max(low, parent + rng.gauss(0, (high - low) / (generation + 5))))
            children.append(child)
        population = children
    best = min(population, key=lambda x: (x - values["target"]) ** 2)
    return result(
        summary={
            "bestVariable": best,
            "objective": (best - values["target"]) ** 2,
            "generationCount": len(history),
        },
        tables=[
            table(
                "Best value by generation",
                [
                    ("generation", "Generation"),
                    ("best", "Best variable"),
                    ("objective", "Squared error"),
                ],
                history,
            )
        ],
        notes=[
            "Bounded real-valued evolutionary search for the explicit quadratic objective (x − target)²; this example objective is supplied as a study input, not a structural response model."
        ],
    )


@feature(
    "studiesDesign.gradientOptimizer",
    "Gradient Optimizer",
    part="settings",
    fields=[
        number("initial", "Initial variable", 1),
        number("target", "Target", 6),
        number("learningRate", "Step size", 0.2, min=0.0001, max=2),
        number("iterations", "Iterations", 30, min=1, max=1000),
    ],
)
def gradient_optimizer(ctx: FeatureContext, values: dict) -> dict:
    """Minimize a scalar quadratic objective by its exact gradient and fixed step size."""
    x, rate = values["initial"], values["learningRate"]
    rows = []
    for iteration in range(int(values["iterations"])):
        gradient = 2 * (x - values["target"])
        x -= rate * gradient
        rows.append(
            {
                "iteration": iteration + 1,
                "variable": x,
                "objective": (x - values["target"]) ** 2,
                "gradient": gradient,
            }
        )
    return result(
        summary={"bestVariable": x, "objective": (x - values["target"]) ** 2},
        tables=[
            table(
                "Gradient iterations",
                [
                    ("iteration", "Iteration"),
                    ("variable", "Variable"),
                    ("objective", "Squared error"),
                    ("gradient", "Gradient"),
                ],
                rows,
            )
        ],
        notes=[
            "Exact gradient of (x − target)²; choose a step size below one for monotone convergence in this scalar case."
        ],
    )


@feature(
    "studiesDesign.surrogateModel",
    "Surrogate Model",
    part="settings",
    fields=[
        text(
            "observations", "Training observations", '[{"x":0,"y":1},{"x":1,"y":3},{"x":2,"y":5}]'
        ),
        number("predictAt", "Predict at x", 3),
    ],
    requires_project=False,
)
def surrogate_model(ctx: FeatureContext, values: dict) -> dict:
    """Fit a least-squares linear response surface to one input and one output."""
    rows = records(values["observations"], "training observations")
    try:
        pairs = [(float(row["x"]), float(row["y"])) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise FeatureInputError("Training observations need numeric x and y values.") from error
    if len(pairs) < 2:
        raise FeatureInputError("Provide at least two training observations.")
    mx, my = sum(x for x, _ in pairs) / len(pairs), sum(y for _, y in pairs) / len(pairs)
    denom = sum((x - mx) ** 2 for x, _ in pairs)
    if denom == 0:
        raise FeatureInputError("Training x values must not all be equal.")
    slope = sum((x - mx) * (y - my) for x, y in pairs) / denom
    intercept = my - slope * mx
    predicted = intercept + slope * values["predictAt"]
    residual = sum((y - intercept - slope * x) ** 2 for x, y in pairs)
    return result(
        summary={
            "intercept": intercept,
            "slope": slope,
            "prediction": predicted,
            "trainingRmse": math.sqrt(residual / len(pairs)),
        },
        tables=[
            table(
                "Surrogate fit",
                [("x", "Input"), ("observed", "Observed"), ("predicted", "Fitted")],
                [{"x": x, "observed": y, "predicted": intercept + slope * x} for x, y in pairs],
            )
        ],
        notes=[
            "Ordinary least-squares straight-line surrogate; predictions outside the training range are extrapolations."
        ],
    )


@feature(
    "studiesDesign.responseSurface",
    "Response Surface",
    part="settings",
    fields=[
        text(
            "observations",
            "Quadratic response data",
            '[{"x":-1,"y":1},{"x":0,"y":0},{"x":1,"y":1},{"x":2,"y":4}]',
        ),
        number("predictAt", "Predict at x", 3),
    ],
    requires_project=False,
)
def response_surface(ctx: FeatureContext, values: dict) -> dict:
    """Fit y = a + b x + c x² by solving the three normal equations."""
    rows = records(values["observations"], "response observations")
    try:
        pairs = [(float(row["x"]), float(row["y"])) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise FeatureInputError("Response observations need numeric x and y values.") from error
    if len(pairs) < 3:
        raise FeatureInputError("A quadratic response surface needs at least three observations.")
    sums = [sum(x**power for x, _ in pairs) for power in range(5)]
    sy = [sum(x**power * y for x, y in pairs) for power in range(3)]
    matrix = [
        [len(pairs), sums[1], sums[2], sy[0]],
        [sums[1], sums[2], sums[3], sy[1]],
        [sums[2], sums[3], sums[4], sy[2]],
    ]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda row: abs(matrix[row][col]))
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        if abs(matrix[col][col]) < 1e-12:
            raise FeatureInputError("The input points do not identify a unique quadratic fit.")
        scale = matrix[col][col]
        matrix[col] = [item / scale for item in matrix[col]]
        for row in range(3):
            if row != col:
                scale = matrix[row][col]
                matrix[row] = [matrix[row][j] - scale * matrix[col][j] for j in range(4)]
    a, b, c = [matrix[i][3] for i in range(3)]
    predicted = a + b * values["predictAt"] + c * values["predictAt"] ** 2
    return result(
        summary={"constant": a, "linear": b, "quadratic": c, "prediction": predicted},
        notes=[
            "Unweighted least-squares quadratic in one variable; extrapolation and higher-dimensional interactions are not represented."
        ],
    )


@feature(
    "studiesDesign.multiCriteriaRank",
    "Multi-Criteria Rank",
    part="settings",
    fields=[
        text(
            "options",
            "Options with criteria",
            '[{"name":"A","cost":100,"carbon":80},{"name":"B","cost":110,"carbon":60}]',
        ),
        text("weights", "Criterion weights JSON", '{"cost":0.6,"carbon":0.4}'),
    ],
    requires_project=False,
)
def multi_criteria_rank(ctx: FeatureContext, values: dict) -> dict:
    """Normalize each criterion to the observed range and rank lower weighted scores first."""
    candidates, weights = (
        records(values["options"], "ranked options"),
        __import__("json").loads(values["weights"]),
    )
    if not isinstance(weights, dict) or not weights:
        raise FeatureInputError("Criterion weights must be a JSON object.")
    keys = list(weights)
    converted = []
    for row in candidates:
        try:
            converted.append(
                {key: float(row[key]) for key in keys} | {"name": row.get("name", "Option")}
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each option needs numeric values for every weighted criterion."
            ) from error
    extrema = {
        key: (min(row[key] for row in converted), max(row[key] for row in converted))
        for key in keys
    }
    output = []
    for row in converted:
        score = 0.0
        for key in keys:
            low, high = extrema[key]
            normalized = (row[key] - low) / (high - low) if high > low else 0.0
            score += normalized * float(weights[key])
        output.append({"name": row["name"], "score": score})
    output.sort(key=lambda row: row["score"])
    return result(
        summary={"rankedCount": len(output), "topOption": output[0]["name"]},
        tables=[
            table(
                "Multi-criteria ranks",
                [("rank", "Rank"), ("name", "Option"), ("score", "Weighted score")],
                [dict(row, rank=i + 1) for i, row in enumerate(output)],
            )
        ],
        notes=[
            "All criteria are treated as costs to minimize and are min-max normalized over the supplied options."
        ],
    )


@feature(
    "studiesDesign.weightingMatrix",
    "Weighting Matrix",
    part="settings",
    fields=[text("matrix", "Pairwise comparison matrix", "[[1,2,4],[0.5,1,3],[0.25,0.333333,1]]")],
    requires_project=False,
)
def weighting_matrix(ctx: FeatureContext, values: dict) -> dict:
    """Estimate criterion priorities from a positive reciprocal pairwise matrix."""
    matrix = __import__("json").loads(values["matrix"])
    if (
        not isinstance(matrix, list)
        or not matrix
        or any(not isinstance(row, list) or len(row) != len(matrix) for row in matrix)
    ):
        raise FeatureInputError("Enter a square numeric pairwise matrix.")
    try:
        a = [[float(v) for v in row] for row in matrix]
    except (TypeError, ValueError) as error:
        raise FeatureInputError("Pairwise matrix entries must be numeric.") from error
    n = len(a)
    if any(a[i][j] <= 0 for i in range(n) for j in range(n)):
        raise FeatureInputError("Pairwise matrix entries must be positive.")
    priorities = [math.prod(row) ** (1 / n) for row in a]
    total = sum(priorities)
    weights = [weight / total for weight in priorities]
    consistency = sum(a[i][j] * weights[j] / weights[i] for i in range(n) for j in range(n)) / n
    return result(
        summary={"criteriaCount": n, "dominantWeight": max(weights), "lambdaEstimate": consistency},
        tables=[
            table(
                "Priority weights",
                [("criterion", "Criterion index"), ("weight", "Priority")],
                [{"criterion": i + 1, "weight": weight} for i, weight in enumerate(weights)],
            )
        ],
        notes=[
            "Geometric-mean priority estimate for positive pairwise judgments; the lambda estimate is descriptive and no acceptability threshold is imposed."
        ],
    )


@feature(
    "studiesDesign.scorecard",
    "Scorecard",
    part="settings",
    fields=[
        text(
            "criteria",
            "Criterion scores",
            '[{"name":"Cost","score":80,"weight":0.5},{"name":"Carbon","score":90,"weight":0.3},{"name":"Performance","score":70,"weight":0.2}]',
        )
    ],
    requires_project=False,
)
def scorecard(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a weighted scorecard from supplied scores and normalized criterion weights."""
    rows = records(values["criteria"], "scorecard criteria")
    try:
        pairs = [(str(row["name"]), float(row["score"]), float(row["weight"])) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise FeatureInputError("Each criterion needs a name, score and weight.") from error
    if any(weight < 0 for _, _, weight in pairs) or sum(w for _, _, w in pairs) <= 0:
        raise FeatureInputError("Weights must be non-negative with a positive total.")
    total = sum(w for _, _, w in pairs)
    output = [
        {
            "criterion": name,
            "score": score,
            "weight": weight / total,
            "contribution": score * weight / total,
        }
        for name, score, weight in pairs
    ]
    return result(
        summary={
            "weightedScore": sum(row["contribution"] for row in output),
            "criterionCount": len(output),
        },
        tables=[
            table(
                "Scorecard contributions",
                [
                    ("criterion", "Criterion"),
                    ("score", "Score"),
                    ("weight", "Weight"),
                    ("contribution", "Contribution"),
                ],
                output,
            )
        ],
        notes=["Scores must share a defined scale; weights are normalized to sum to one."],
    )
