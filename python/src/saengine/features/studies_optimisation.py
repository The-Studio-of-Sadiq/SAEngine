"""Studies Optimisation - bounded design studies, topology and cost trade-offs."""

from __future__ import annotations

import csv
import io
import json
import math

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
    records,
    study_path,
    write_json,
    write_text,
)


@feature(
    "studiesOptimisation.defineObjective",
    "Define Objective",
    part="settings",
    fields=[
        text("name", "Objective name", "embodiedCarbon"),
        select("direction", "Direction", [("min", "Minimize"), ("max", "Maximize")], "min"),
        text("unit", "Objective unit", "kg CO2e"),
    ],
    requires_project=False,
)
def define_objective(ctx: FeatureContext, values: dict) -> dict:
    """Create an explicit objective definition with direction and measurement unit."""
    if not values["name"].strip():
        raise FeatureInputError("Enter an objective name.")
    return result(
        summary={
            "name": values["name"].strip(),
            "direction": values["direction"],
            "unit": values["unit"],
        },
        notes=[
            "The objective records how candidate outputs will be ranked; it does not calculate a structural response."
        ],
    )


@feature(
    "studiesOptimisation.objectiveWeight",
    "Objective Weight",
    part="settings",
    fields=[
        text(
            "objectives",
            "Objective weights",
            '[{"objective":"cost","weight":0.6},{"objective":"carbon","weight":0.4}]',
        )
    ],
    requires_project=False,
)
def objective_weight(ctx: FeatureContext, values: dict) -> dict:
    """Normalize multi-objective weights for use in a weighted decision score."""
    rows = records(values["objectives"], "objective weights")
    try:
        weights = [float(row["weight"]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise FeatureInputError("Each objective needs a numeric weight.") from error
    if any(weight < 0 for weight in weights) or sum(weights) <= 0:
        raise FeatureInputError("Weights must be non-negative and have a positive sum.")
    total = sum(weights)
    output = [
        {
            "objective": row.get("objective", "Objective"),
            "weight": weight,
            "normalizedWeight": weight / total,
        }
        for row, weight in zip(rows, weights, strict=True)
    ]
    return result(
        summary={"objectiveCount": len(output), "normalizedSum": 1.0},
        tables=[
            table(
                "Objective weights",
                [
                    ("objective", "Objective"),
                    ("weight", "Input weight"),
                    ("normalizedWeight", "Normalized weight"),
                ],
                output,
            )
        ],
        notes=[
            "The weights are normalized to one; candidate criteria must be put on comparable scales before aggregation."
        ],
    )


@feature(
    "studiesOptimisation.addConstraint",
    "Add Constraint",
    part="settings",
    fields=[
        text(
            "constraints",
            "Constraint limits",
            '[{"name":"drift","minimum":0,"maximum":0.02,"unit":"ratio"},{"name":"cost","maximum":1000000,"unit":"currency"}]',
        )
    ],
    requires_project=False,
)
def add_constraint(ctx: FeatureContext, values: dict) -> dict:
    """Validate a set of finite lower and upper optimization bounds."""
    rows = records(values["constraints"], "constraints")
    output = []
    for row in rows:
        low, high = row.get("minimum"), row.get("maximum")
        if low is None and high is None:
            raise FeatureInputError("Each constraint needs a minimum, a maximum or both.")
        try:
            low = float(low) if low is not None else None
            high = float(high) if high is not None else None
        except (TypeError, ValueError) as error:
            raise FeatureInputError("Constraint bounds must be numeric.") from error
        if low is not None and high is not None and low > high:
            raise FeatureInputError("A constraint minimum cannot exceed its maximum.")
        output.append(
            {
                "name": row.get("name", "Constraint"),
                "minimum": low,
                "maximum": high,
                "unit": row.get("unit", ""),
            }
        )
    return result(
        summary={"constraintCount": len(output)},
        tables=[
            table(
                "Optimization constraints",
                [
                    ("name", "Constraint"),
                    ("minimum", "Minimum"),
                    ("maximum", "Maximum"),
                    ("unit", "Unit"),
                ],
                output,
            )
        ],
        notes=[
            "Bounds are retained as supplied and can be evaluated against candidate response records."
        ],
    )


@feature(
    "studiesOptimisation.setTarget",
    "Set Target",
    part="settings",
    fields=[
        text(
            "targets",
            "Target values",
            '[{"quantity":"cost","target":950000,"tolerance":50000,"unit":"currency"},{"quantity":"drift","target":0.015,"tolerance":0.002,"unit":"ratio"}]',
        )
    ],
    requires_project=False,
)
def set_target(ctx: FeatureContext, values: dict) -> dict:
    """Calculate acceptable numeric target bands from target values and absolute tolerances."""
    output = []
    for item in records(values["targets"], "design targets"):
        try:
            target, tolerance = float(item["target"]), float(item["tolerance"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each target needs numeric target and tolerance values."
            ) from error
        if tolerance < 0:
            raise FeatureInputError("Target tolerances must be non-negative.")
        output.append(
            {
                "quantity": item.get("quantity", "Quantity"),
                "target": target,
                "minimum": target - tolerance,
                "maximum": target + tolerance,
                "unit": item.get("unit", ""),
            }
        )
    return result(
        summary={"targetCount": len(output)},
        tables=[
            table(
                "Target bands",
                [
                    ("quantity", "Quantity"),
                    ("minimum", "Minimum"),
                    ("target", "Target"),
                    ("maximum", "Maximum"),
                    ("unit", "Unit"),
                ],
                output,
            )
        ],
        notes=["The tolerance is symmetric and absolute in the stated unit."],
    )


@feature(
    "studiesOptimisation.algorithmSelect",
    "Algorithm Select",
    part="settings",
    fields=[
        select(
            "algorithm",
            "Search algorithm",
            [
                ("grid", "Grid search"),
                ("random", "Random search"),
                ("coordinate", "Coordinate descent"),
                ("genetic", "Genetic search"),
            ],
            "grid",
        ),
        number("variables", "Variable count", 3, min=1),
        number("evaluations", "Evaluation budget", 1000, min=1),
    ],
    requires_project=False,
)
def algorithm_select(ctx: FeatureContext, values: dict) -> dict:
    """Estimate search-space coverage and evaluations per variable for a selected algorithm."""
    count, budget = int(values["variables"]), int(values["evaluations"])
    if values["algorithm"] == "grid":
        levels = math.floor(budget ** (1 / count))
        coverage = levels**count
    elif values["algorithm"] == "coordinate":
        levels = None
        coverage = budget
    else:
        levels = None
        coverage = budget
    return result(
        summary={
            "algorithm": values["algorithm"],
            "variableCount": count,
            "evaluationBudget": budget,
            "estimatedGridLevelsPerVariable": levels,
            "plannedEvaluations": coverage,
        },
        notes=[
            "Grid coverage is the largest complete Cartesian grid that fits the evaluation budget; other algorithms use the budget as a run count."
        ],
    )


@feature(
    "studiesOptimisation.designVariables",
    "Design Variables",
    part="settings",
    fields=[
        text(
            "variables",
            "Variables with bounds",
            '[{"name":"spanM","lower":5,"upper":8,"unit":"m"},{"name":"depthMm","lower":400,"upper":700,"unit":"mm"}]',
        )
    ],
    requires_project=False,
)
def design_variables(ctx: FeatureContext, values: dict) -> dict:
    """Validate bounded design variables and calculate their normalized midpoints."""
    output = []
    for row in records(values["variables"], "design variables"):
        try:
            low, high = float(row["lower"]), float(row["upper"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each design variable needs lower and upper numeric bounds."
            ) from error
        if high <= low:
            raise FeatureInputError("Every upper bound must exceed its lower bound.")
        output.append(
            {
                "name": row.get("name", "Variable"),
                "lower": low,
                "upper": high,
                "midpoint": (low + high) / 2,
                "unit": row.get("unit", ""),
            }
        )
    return result(
        summary={"variableCount": len(output), "dimensionCount": len(output)},
        tables=[
            table(
                "Bounded variables",
                [
                    ("name", "Variable"),
                    ("lower", "Lower"),
                    ("midpoint", "Midpoint"),
                    ("upper", "Upper"),
                    ("unit", "Unit"),
                ],
                output,
            )
        ],
        notes=["Midpoints are arithmetic centers of the declared variable intervals."],
    )


@feature(
    "studiesOptimisation.generationCount",
    "Generation Count",
    part="settings",
    fields=[
        number("population", "Population size", 40, min=2, max=5000),
        number("generations", "Generation count", 60, min=1, max=10000),
        number("eliteFraction", "Elite fraction", 0.1, min=0, max=0.9),
    ],
    requires_project=False,
)
def generation_count(ctx: FeatureContext, values: dict) -> dict:
    """Estimate candidate evaluations for a generational population with an explicit elite share."""
    population, generations = int(values["population"]), int(values["generations"])
    elite = math.ceil(population * values["eliteFraction"])
    return result(
        summary={
            "population": population,
            "generations": generations,
            "evaluations": population * generations,
            "elitePerGeneration": elite,
            "newCandidates": (population - elite) * generations,
        },
        notes=[
            "The total evaluation estimate assumes the initial population and every later generation are fully evaluated."
        ],
    )


@feature(
    "studiesOptimisation.runOptimisation",
    "Run Optimisation",
    part="settings",
    fields=[
        text(
            "candidates",
            "Candidate designs",
            '[{"name":"A","cost":100,"carbon":80},{"name":"B","cost":120,"carbon":50},{"name":"C","cost":110,"carbon":70}]',
        ),
        text("objective", "Minimize objective", "cost"),
        text("constraints", "Constraint upper bounds JSON", '{"carbon":75}'),
    ],
    requires_project=False,
)
def run_optimisation(ctx: FeatureContext, values: dict) -> dict:
    """Select the lowest-cost candidate that satisfies explicit upper-bound constraints."""
    candidates, limits = (
        records(values["candidates"], "optimization candidates"),
        json.loads(values["constraints"]),
    )
    feasible, output = [], []
    for candidate in candidates:
        try:
            objective = float(candidate[values["objective"]])
            passes = all(float(candidate[key]) <= float(limit) for key, limit in limits.items())
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each candidate needs numeric objective and constrained values."
            ) from error
        item = {
            "name": candidate.get("name", "Candidate"),
            "objective": objective,
            "feasible": passes,
        }
        output.append(item)
        if passes:
            feasible.append(item)
    if not feasible:
        raise FeatureInputError("No supplied candidate meets all upper-bound constraints.")
    best = min(feasible, key=lambda item: item["objective"])
    return result(
        summary={
            "evaluatedCandidates": len(output),
            "feasibleCandidates": len(feasible),
            "bestCandidate": best["name"],
            "bestObjective": best["objective"],
        },
        tables=[
            table(
                "Candidate screening",
                [
                    ("name", "Candidate"),
                    ("objective", values["objective"]),
                    ("feasible", "Feasible"),
                ],
                output,
            )
        ],
        notes=["This ranks a finite supplied candidate set; it does not modify the design model."],
    )


@feature(
    "studiesOptimisation.paretoFront",
    "Pareto Front",
    part="settings",
    fields=[
        text(
            "candidates",
            "Candidates",
            '[{"name":"A","cost":100,"carbon":80},{"name":"B","cost":110,"carbon":60},{"name":"C","cost":120,"carbon":90}]',
        ),
        text("minimized", "Minimized objective names", "cost,carbon"),
    ],
    requires_project=False,
)
def pareto_front(ctx: FeatureContext, values: dict) -> dict:
    """Return non-dominated candidates for all listed minimization objectives."""
    rows, objectives = (
        records(values["candidates"], "optimization candidates"),
        [key.strip() for key in values["minimized"].split(",") if key.strip()],
    )
    if not objectives:
        raise FeatureInputError("Provide at least one objective to minimize.")
    converted = []
    for row in rows:
        try:
            converted.append((row, [float(row[key]) for key in objectives]))
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Every candidate needs numeric values for all objectives."
            ) from error
    front = []
    for candidate, scores in converted:
        is_dominated = any(
            other is not candidate
            and all(a <= b for a, b in zip(other_scores, scores, strict=True))
            and any(a < b for a, b in zip(other_scores, scores, strict=True))
            for other, other_scores in converted
        )
        if not is_dominated:
            front.append(
                {
                    "name": candidate.get("name", "Candidate"),
                    **dict(zip(objectives, scores, strict=True)),
                }
            )
    return result(
        summary={"candidateCount": len(rows), "frontCount": len(front)},
        tables=[
            table(
                "Pareto-optimal candidates",
                [("name", "Candidate"), *[(key, key.title()) for key in objectives]],
                front,
            )
        ],
        notes=[
            "All objectives are minimized; candidates are nondominated if no other candidate is no worse in all objectives and better in at least one."
        ],
    )


@feature(
    "studiesOptimisation.bestDesign",
    "Best Design",
    part="settings",
    fields=[
        text(
            "designs",
            "Candidate designs",
            '[{"name":"A","score":82,"massKg":1200},{"name":"B","score":91,"massKg":1300}]',
        ),
        select(
            "direction",
            "Score direction",
            [("max", "Higher is better"), ("min", "Lower is better")],
            "max",
        ),
    ],
    requires_project=False,
)
def best_design(ctx: FeatureContext, values: dict) -> dict:
    """Select the supplied design with the best numeric objective score."""
    rows = records(values["designs"], "candidate designs")
    try:
        for row in rows:
            row["score"] = float(row["score"])
    except (KeyError, TypeError, ValueError) as error:
        raise FeatureInputError("Each candidate needs a numeric score.") from error
    key = max if values["direction"] == "max" else min
    chosen = key(rows, key=lambda row: row["score"])
    return result(
        summary={"bestDesign": chosen.get("name", "Design"), "score": chosen["score"]},
        tables=[
            table(
                "Design ranking",
                [("rank", "Rank"), ("name", "Design"), ("score", "Score")],
                [
                    dict(row, rank=i + 1)
                    for i, row in enumerate(
                        sorted(
                            rows, key=lambda row: row["score"], reverse=values["direction"] == "max"
                        )
                    )
                ],
            )
        ],
        notes=["Candidate scores and score direction are supplied by the engineer."],
    )


@feature(
    "studiesOptimisation.applyBest",
    "Apply Best",
    part="settings",
    fields=[
        text(
            "design",
            "Best design JSON",
            '{"name":"Scheme B","variables":{"spanM":6,"depthMm":550},"objectives":{"cost":950000}}',
        )
    ],
)
def apply_best(ctx: FeatureContext, values: dict) -> dict:
    """Save the reviewed best-design record for traceability without mutating structural model inputs."""
    best = json.loads(values["design"])
    if not isinstance(best, dict) or not best.get("variables"):
        raise FeatureInputError("Best design must be a JSON object with a variables object.")
    best["appliedToStudy"] = True
    path = write_json(ctx, study_path("selected-best-design"), best)
    return result(
        summary={
            "design": best.get("name", "Selected design"),
            "variableCount": len(best["variables"]),
            "recordPath": path,
        },
        notes=[
            f"The selected design record was saved to {path}; structural model inputs are not rewritten."
        ],
    )


@feature(
    "studiesOptimisation.exportResults",
    "Export Results",
    part="settings",
    fields=[
        text(
            "results",
            "Optimization results",
            '[{"name":"A","cost":100,"carbon":80,"feasible":true},{"name":"B","cost":110,"carbon":60,"feasible":true}]',
        ),
        text("filename", "CSV filename", "optimisation-results"),
    ],
)
def export_results(ctx: FeatureContext, values: dict) -> dict:
    """Write optimization candidate records as a UTF-8 CSV deliverable."""
    rows = records(values["results"], "optimization results")
    if ctx.root is None:
        raise FeatureInputError("Open a project to export optimization results.")
    columns = list(dict.fromkeys(key for row in rows for key in row))
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    name = (
        "".join(char for char in values["filename"] if char.isalnum() or char in "-_")
        or "optimisation-results"
    )
    path = write_text(ctx, f"11 Exports/{name}.csv", buffer.getvalue())
    return result(
        summary={"candidateCount": len(rows), "outputPath": path},
        notes=[f"Optimization results exported to {path}."],
    )


@feature(
    "studiesOptimisation.densityMethod",
    "Density Method",
    part="settings",
    fields=[
        text("densities", "Element density fractions", "0.5,0.7,0.9,1"),
        number("penalty", "SIMP penalty exponent", 3, min=1, max=5),
        number("minimumDensity", "Minimum relative density", 0.001, min=0.0001, max=1),
    ],
    requires_project=False,
)
def density_method(ctx: FeatureContext, values: dict) -> dict:
    """Apply the solid-isotropic-material penalization law to a supplied density field."""
    densities = [
        min(1, max(values["minimumDensity"], x))
        for x in (
            float(item) for item in values["densities"].replace(";", ",").split(",") if item.strip()
        )
    ]
    if not densities or any(x < 0 or x > 1 for x in densities):
        raise FeatureInputError("Provide density fractions from zero to one.")
    rows = [
        {"element": i + 1, "density": rho, "relativeStiffness": rho ** values["penalty"]}
        for i, rho in enumerate(densities)
    ]
    return result(
        summary={
            "elementCount": len(rows),
            "meanRelativeStiffness": sum(row["relativeStiffness"] for row in rows) / len(rows),
        },
        tables=[
            table(
                "Penalized densities",
                [
                    ("element", "Element"),
                    ("density", "Density"),
                    ("relativeStiffness", "Relative stiffness"),
                ],
                rows,
            )
        ],
        notes=[
            "SIMP interpolation E/E0 = max(rho, rho_min)^p; this reports material interpolation and does not solve structural equilibrium."
        ],
    )


@feature(
    "studiesOptimisation.volumeFraction",
    "Volume Fraction",
    part="settings",
    fields=[
        text("densities", "Element density fractions", "0.5,0.7,0.9,1"),
        number("target", "Target volume fraction", 0.7, min=0, max=1),
    ],
    requires_project=False,
)
def volume_fraction(ctx: FeatureContext, values: dict) -> dict:
    """Calculate mean material volume fraction and its difference from a target."""
    data = [
        float(item) for item in values["densities"].replace(";", ",").split(",") if item.strip()
    ]
    if not data or any(value < 0 or value > 1 for value in data):
        raise FeatureInputError("Density fractions must be between zero and one.")
    actual = sum(data) / len(data)
    return result(
        summary={
            "actualVolumeFraction": actual,
            "targetVolumeFraction": values["target"],
            "difference": actual - values["target"],
            "meetsTarget": actual <= values["target"],
        },
        notes=[
            "Equal element volumes are assumed; for a nonuniform mesh, use element-volume-weighted densities."
        ],
    )


@feature(
    "studiesOptimisation.minimumLength",
    "Minimum Length",
    part="settings",
    fields=[
        number("elementLength", "Characteristic element length", 500, unit="mm", min=0.001),
        number("minimumMemberWidth", "Minimum member width", 150, unit="mm", min=0),
        number("minimumFeatureElements", "Elements across feature", 3, min=1, max=100),
    ],
    requires_project=False,
)
def minimum_length(ctx: FeatureContext, values: dict) -> dict:
    """Check whether a target minimum member feature spans enough characteristic mesh lengths."""
    needed = values["minimumFeatureElements"] * values["elementLength"]
    return result(
        summary={
            "requiredFeatureWidthMm": needed,
            "availableFeatureWidthMm": values["minimumMemberWidth"],
            "featureResolutionRatio": values["minimumMemberWidth"] / values["elementLength"],
            "resolved": values["minimumMemberWidth"] >= needed,
        },
        notes=[
            "This is a mesh-resolution screening rule; the selected number of elements across a feature is a user assumption."
        ],
    )


@feature(
    "studiesOptimisation.filterRadius",
    "Filter Radius",
    part="settings",
    fields=[
        number("radius", "Filter radius", 1200, unit="mm", min=0.001),
        number("elementSize", "Characteristic element size", 400, unit="mm", min=0.001),
    ],
    requires_project=False,
)
def filter_radius(ctx: FeatureContext, values: dict) -> dict:
    """Estimate the number of element lengths covered by a topology-design filter radius."""
    ratio = values["radius"] / values["elementSize"]
    return result(
        summary={
            "filterRadiusMm": values["radius"],
            "elementSizeMm": values["elementSize"],
            "radiusInElements": ratio,
            "integerStencilRadius": math.ceil(ratio),
        },
        notes=[
            "The ratio is a geometric neighborhood descriptor; actual filters use mesh adjacency and element areas."
        ],
    )


@feature(
    "studiesOptimisation.morphingMesh",
    "Morphing Mesh",
    part="settings",
    fields=[
        text("nodes", "Node records", '[{"id":1,"x":0,"y":0,"z":0},{"id":2,"x":1000,"y":0,"z":0}]'),
        text(
            "displacements",
            "Node displacement records",
            '[{"id":1,"dx":0,"dy":0,"dz":0},{"id":2,"dx":0,"dy":0,"dz":50}]',
        ),
    ],
    requires_project=False,
)
def morphing_mesh(ctx: FeatureContext, values: dict) -> dict:
    """Apply explicitly supplied nodal displacements to coordinate records for a deformed mesh view."""
    nodes = records(values["nodes"], "mesh nodes")
    movements = {
        str(row["id"]): row for row in records(values["displacements"], "node displacements")
    }
    output = []
    for node in nodes:
        move = movements.get(str(node.get("id")), {})
        coordinates = {
            axis: float(node.get(axis, 0)) + float(move.get("d" + axis, 0))
            for axis in ("x", "y", "z")
        }
        output.append({"id": node.get("id"), **coordinates})
    return result(
        summary={
            "nodeCount": len(output),
            "movedNodeCount": sum(str(node.get("id")) in movements for node in nodes),
        },
        tables=[
            table(
                "Morphed coordinates", [("id", "Node"), ("x", "X"), ("y", "Y"), ("z", "Z")], output
            )
        ],
        notes=[
            "Coordinates equal original geometry plus supplied displacement; no solver results or scale factor are inferred."
        ],
    )


@feature(
    "studiesOptimisation.boundaryNodes",
    "Boundary Nodes",
    part="settings",
    fields=[
        text(
            "nodes",
            "Node coordinates",
            '[{"id":1,"x":0,"y":0,"z":0},{"id":2,"x":1000,"y":0,"z":0},{"id":3,"x":500,"y":500,"z":0}]',
        ),
        number("tolerance", "Boundary coordinate tolerance", 1, unit="mm", min=0),
    ],
)
def boundary_nodes(ctx: FeatureContext, values: dict) -> dict:
    """Identify node identifiers on any coordinate-extreme plane within a stated tolerance."""
    nodes = records(values["nodes"], "mesh nodes")
    coords = {axis: [float(node[axis]) for node in nodes] for axis in ("x", "y", "z")}
    extrema = {axis: (min(vals), max(vals)) for axis, vals in coords.items()}
    output = []
    for node in nodes:
        on_boundary = [
            axis
            for axis in extrema
            if min(
                abs(float(node[axis]) - extrema[axis][0]), abs(float(node[axis]) - extrema[axis][1])
            )
            <= values["tolerance"]
        ]
        if on_boundary:
            output.append({"id": node.get("id"), "boundaryAxes": ", ".join(on_boundary)})
    return result(
        summary={"nodeCount": len(nodes), "boundaryNodeCount": len(output)},
        tables=[
            table("Boundary nodes", [("id", "Node"), ("boundaryAxes", "Boundary axes")], output)
        ],
        notes=[
            "Boundary means lying on an axis-aligned coordinate-extreme plane within the chosen tolerance."
        ],
    )


@feature(
    "studiesOptimisation.smoothSurface",
    "Smooth Surface",
    part="settings",
    fields=[
        text("vertices", "Surface vertex values", "0,0,1\n1,0,2\n2,0,3\n0,1,1\n1,1,2\n2,1,3"),
        number("blend", "Neighbor blend fraction", 0.5, min=0, max=1),
    ],
    requires_project=False,
)
def smooth_surface(ctx: FeatureContext, values: dict) -> dict:
    """Apply one synchronous four-neighbor averaging pass to a rectangular x,y,value grid."""
    points = []
    for line in values["vertices"].splitlines():
        if line.strip():
            parts = [float(x) for x in line.replace(",", " ").split()]
            if len(parts) != 3:
                raise FeatureInputError("Every vertex row needs x, y and value.")
            points.append(parts)
    if len(points) < 4:
        raise FeatureInputError("Provide at least four surface vertices.")
    by_xy = {(x, y): value for x, y, value in points}
    output = []
    for x, y, value in points:
        neighbors = [
            by_xy[(nx, ny)]
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            if (nx, ny) in by_xy
        ]
        mean = sum(neighbors) / len(neighbors) if neighbors else value
        output.append(
            {
                "x": x,
                "y": y,
                "original": value,
                "smoothed": value + values["blend"] * (mean - value),
            }
        )
    return result(
        summary={
            "vertexCount": len(output),
            "changedVertices": sum(row["original"] != row["smoothed"] for row in output),
        },
        tables=[
            table(
                "Smoothed grid",
                [
                    ("x", "X"),
                    ("y", "Y"),
                    ("original", "Original value"),
                    ("smoothed", "Smoothed value"),
                ],
                output,
            )
        ],
        notes=[
            "One pass uses only orthogonal unit-grid neighbors present in the input; the original field is preserved in the result."
        ],
    )


@feature(
    "studiesOptimisation.shapeSensitivity",
    "Shape Sensitivity",
    part="settings",
    fields=[
        text(
            "perturbations",
            "Perturbed geometry response",
            '[{"parameter":"depth","minus":9.5,"base":10,"plus":10.7,"step":50,"unit":"mm"}]',
        )
    ],
    requires_project=False,
)
def shape_sensitivity(ctx: FeatureContext, values: dict) -> dict:
    """Estimate central finite-difference response sensitivity to each geometry parameter."""
    output = []
    for row in records(values["perturbations"], "shape perturbations"):
        try:
            minus, base, plus, step = (float(row[key]) for key in ("minus", "base", "plus", "step"))
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each perturbation needs minus, base, plus and positive step values."
            ) from error
        if step <= 0:
            raise FeatureInputError("Perturbation step must be positive.")
        output.append(
            {
                "parameter": row.get("parameter", "Parameter"),
                "centralDerivative": (plus - minus) / (2 * step),
                "minusSlope": (base - minus) / step,
                "plusSlope": (plus - base) / step,
                "unit": f"response/{row.get('unit', 'unit')}",
            }
        )
    return result(
        summary={"parameterCount": len(output)},
        tables=[
            table(
                "Shape sensitivities",
                [
                    ("parameter", "Parameter"),
                    ("centralDerivative", "Central derivative"),
                    ("minusSlope", "Lower-side slope"),
                    ("plusSlope", "Upper-side slope"),
                    ("unit", "Derivative unit"),
                ],
                output,
            )
        ],
        notes=[
            "Central finite difference uses equal-sized positive and negative perturbations around the supplied base response."
        ],
    )


@feature(
    "studiesOptimisation.materialCost",
    "Material Cost",
    part="materials",
    fields=[
        text(
            "quantities",
            "Material quantity and rate rows",
            '[{"material":"Concrete","quantity":120,"unit":"m3","rate":110},{"material":"Steel","quantity":18,"unit":"t","rate":850}]',
        )
    ],
    requires_project=False,
)
def material_cost(ctx: FeatureContext, values: dict) -> dict:
    """Calculate direct material costs from measured quantities and supplied unit rates."""
    rows = records(values["quantities"], "material quantities")
    output = []
    for row in rows:
        try:
            quantity, rate = float(row["quantity"]), float(row["rate"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Every material needs numeric quantity and rate values."
            ) from error
        output.append(
            {
                "material": row.get("material", "Material"),
                "quantity": quantity,
                "unit": row.get("unit", ""),
                "rate": rate,
                "cost": quantity * rate,
            }
        )
    return result(
        summary={
            "materialCount": len(output),
            "totalMaterialCost": sum(row["cost"] for row in output),
        },
        tables=[
            table(
                "Material cost plan",
                [
                    ("material", "Material"),
                    ("quantity", "Quantity"),
                    ("unit", "Unit"),
                    ("rate", "Unit rate"),
                    ("cost", "Cost"),
                ],
                output,
            )
        ],
        notes=[
            "Unit rates are supplied inputs; waste, procurement tax and price escalation are not included."
        ],
    )


@feature(
    "studiesOptimisation.fabricationCost",
    "Fabrication Cost",
    part="settings",
    fields=[
        number("steelMass", "Steel mass", 20, unit="t", min=0),
        number("ratePerTonne", "Shop rate", 450, unit="currency/t", min=0),
        number("setupHours", "Setup hours", 16, unit="h", min=0),
        number("hourlyRate", "Setup labor rate", 55, unit="currency/h", min=0),
        number("complexityFactor", "Complexity multiplier", 1.2, min=0),
    ],
)
def fabrication_cost(ctx: FeatureContext, values: dict) -> dict:
    """Estimate shop fabrication cost from steel tonnage, setup labor and a stated complexity factor."""
    base = (
        values["steelMass"] * values["ratePerTonne"] + values["setupHours"] * values["hourlyRate"]
    )
    return result(
        summary={
            "baseFabricationCost": base,
            "complexityFactor": values["complexityFactor"],
            "estimatedFabricationCost": base * values["complexityFactor"],
        },
        notes=[
            "Mass-based shop rate plus fixed setup labor, multiplied by the user's complexity factor; connection-specific rates and coating are excluded."
        ],
    )


@feature(
    "studiesOptimisation.erectionCost",
    "Erection Cost",
    part="settings",
    fields=[
        number("members", "Members erected", 250, min=0),
        number("crewHours", "Crew hours", 1200, unit="h", min=0),
        number("hourlyRate", "Crew cost rate", 75, unit="currency/h", min=0),
        number("craneDays", "Crane days", 20, unit="day", min=0),
        number("craneDailyCost", "Crane cost", 1800, unit="currency/day", min=0),
        number("travel", "Travel and mobilization", 12000, unit="currency", min=0),
    ],
    requires_project=False,
)
def erection_cost(ctx: FeatureContext, values: dict) -> dict:
    """Sum erection labor, crane hire and mobilization into a construction-phase estimate."""
    labor = values["crewHours"] * values["hourlyRate"]
    crane = values["craneDays"] * values["craneDailyCost"]
    return result(
        summary={
            "memberCount": values["members"],
            "laborCost": labor,
            "craneCost": crane,
            "mobilizationCost": values["travel"],
            "erectionCost": labor + crane + values["travel"],
            "costPerMember": (labor + crane + values["travel"]) / values["members"]
            if values["members"]
            else None,
        },
        notes=[
            "Crew hours, crane duration and mobilization are explicit estimate inputs; weather, overtime and temporary works are excluded."
        ],
    )


@feature(
    "studiesOptimisation.carbonFootprint",
    "Carbon Footprint",
    part="materials",
    fields=[
        text(
            "materials",
            "Material carbon records",
            '[{"material":"Concrete","quantity":120,"unit":"m3","factor":280},{"material":"Steel","quantity":18,"unit":"t","factor":1700}]',
        )
    ],
    requires_project=False,
)
def carbon_footprint(ctx: FeatureContext, values: dict) -> dict:
    """Sum embodied material carbon from supplied quantities and declared emission factors."""
    output = []
    for row in records(values["materials"], "material carbon records"):
        try:
            quantity, factor = float(row["quantity"]), float(row["factor"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each material needs numeric quantity and factor inputs."
            ) from error
        output.append(
            {
                "material": row.get("material", "Material"),
                "quantity": quantity,
                "unit": row.get("unit", ""),
                "factor": factor,
                "carbonKgCo2e": quantity * factor,
            }
        )
    return result(
        summary={
            "materialCount": len(output),
            "embodiedCarbonKgCo2e": sum(row["carbonKgCo2e"] for row in output),
        },
        tables=[
            table(
                "Material carbon",
                [
                    ("material", "Material"),
                    ("quantity", "Quantity"),
                    ("unit", "Unit"),
                    ("factor", "Factor"),
                    ("carbonKgCo2e", "Embodied carbon", "kg CO2e"),
                ],
                output,
            )
        ],
        notes=[
            "Factors and quantities must share a compatible declared unit and boundary; reuse, transport and end-of-life are not included unless the factor includes them."
        ],
    )
