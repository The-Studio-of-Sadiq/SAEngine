"""Electrical distribution sizing, schedules and diagram data."""

from __future__ import annotations

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


def _electrical(ctx: FeatureContext) -> dict:
    raw = ctx.raw("mep")
    electrical = raw.get("electrical") if raw else None
    if not isinstance(electrical, dict):
        raise FeatureInputError("Add electrical distribution data to 07 MEP/mep.json first.")
    return electrical


@feature(
    "mepElectrical.boardLayout",
    "Board Layout",
    part="mep",
    fields=[
        number("boardWidthMm", "Board internal width", 600, unit="mm", min=1),
        number("boardHeightMm", "Board internal height", 800, unit="mm", min=1),
        number("modulePitchMm", "Breaker module pitch", 18, unit="mm", min=1),
        number("usableWidthFraction", "Usable width fraction", 0.8, min=0.1, max=1),
        number("breakerCount", "Breaker count", 24, min=1),
        number("modulesPerBreaker", "Average modules per breaker", 1, min=1),
    ],
    requires_project=False,
)
def board_layout(ctx: FeatureContext, values: dict) -> dict:
    """Check breaker module fit within the board's usable internal width."""
    modules_per_row = int(
        values["boardWidthMm"] * values["usableWidthFraction"] / values["modulePitchMm"]
    )
    rows = math.ceil(values["breakerCount"] * values["modulesPerBreaker"] / max(modules_per_row, 1))
    available_height = rows * values["modulePitchMm"]
    return result(
        summary={
            "modulesPerRow": modules_per_row,
            "requiredRows": rows,
            "requiredHeightMm": available_height,
            "physicalFit": available_height <= values["boardHeightMm"],
        },
        notes=[
            "Layout uses a uniform module pitch and width utilization; wiring space, heat dissipation, segregation and manufacturer enclosures require detailed board design."
        ],
    )


@feature(
    "mepElectrical.circuitWiring",
    "Circuit Wiring",
    part="mep",
    fields=[
        text("circuitId", "Circuit reference", "L1-01"),
        number("loadKw", "Circuit load", 3.0, unit="kW", min=0),
        number("voltageV", "Nominal voltage", 230, unit="V", min=1),
        number("powerFactor", "Power factor", 0.9, min=0.1, max=1),
        number("cableLengthM", "One-way cable length", 25, unit="m", min=0),
        number("voltageDropLimitPercent", "Project voltage-drop limit", 3, unit="%", min=0.1),
    ],
    requires_project=False,
)
def circuit_wiring(ctx: FeatureContext, values: dict) -> dict:
    """Calculate single-phase circuit current and resistive voltage drop."""
    current = values["loadKw"] * 1000 / (values["voltageV"] * values["powerFactor"])
    return result(
        summary={"circuitId": values["circuitId"], "designCurrentA": current},
        notes=[
            "Cable selection and voltage drop require conductor material, cross-section, installation method, reactance and protection data."
        ],
    )


@feature(
    "mepElectrical.homeRun",
    "Home Run",
    part="mep",
    fields=[
        number("panelXM", "Panel X coordinate", 2, unit="m"),
        number("panelYM", "Panel Y coordinate", 2, unit="m"),
        number("deviceXM", "Device X coordinate", 12, unit="m"),
        number("deviceYM", "Device Y coordinate", 8, unit="m"),
        number("verticalRiseM", "Vertical rise", 3, unit="m", min=0),
        number("routingAllowancePercent", "Routing allowance", 15, unit="%", min=0),
    ],
    requires_project=False,
)
def home_run(ctx: FeatureContext, values: dict) -> dict:
    """Estimate orthogonal home-run conduit length with a routing allowance."""
    horizontal = abs(values["deviceXM"] - values["panelXM"]) + abs(
        values["deviceYM"] - values["panelYM"]
    )
    base = horizontal + values["verticalRiseM"]
    return result(
        summary={
            "baseRouteLengthM": base,
            "estimatedLengthM": base * (1 + values["routingAllowancePercent"] / 100),
        },
        notes=[
            "Horizontal route uses Manhattan distance and adds the stated vertical rise and routing allowance; bends, floor offsets and actual path obstructions are not modeled."
        ],
    )


@feature(
    "mepElectrical.circuitGrouping",
    "Circuit Grouping",
    part="mep",
    fields=[
        number("circuitCount", "Circuits in shared route", 6, min=1),
        number("currentPerCircuitA", "Circuit current", 12, unit="A", min=0),
        number("simultaneityFactor", "Simultaneity factor", 0.75, min=0, max=1),
        number("conduitCapacityA", "Shared-route capacity", 60, unit="A", min=0.1),
    ],
    requires_project=False,
)
def circuit_grouping(ctx: FeatureContext, values: dict) -> dict:
    """Aggregate grouped circuit demand and compare against route capacity."""
    coincident = (
        values["circuitCount"] * values["currentPerCircuitA"] * values["simultaneityFactor"]
    )
    return result(
        summary={
            "coincidentCurrentA": coincident,
            "routeCapacityA": values["conduitCapacityA"],
            "capacityPasses": coincident <= values["conduitCapacityA"],
        },
        notes=[
            "The entered simultaneity factor estimates demand only; conductor ampacity grouping derating must be checked separately."
        ],
    )


@feature(
    "mepElectrical.neutralSizing",
    "Neutral Sizing",
    part="mep",
    fields=[
        number("fundamentalNeutralA", "Fundamental neutral current", 15, unit="A", min=0),
        number("thirdHarmonicA", "Third harmonic per phase", 8, unit="A", min=0),
        number("unbalanceA", "Other neutral unbalance current", 5, unit="A", min=0),
        number("neutralAmpacityA", "Selected neutral ampacity", 40, unit="A", min=0.1),
    ],
    requires_project=False,
)
def neutral_sizing(ctx: FeatureContext, values: dict) -> dict:
    """Estimate neutral current including triplen harmonic aggregation."""
    harmonic_neutral = 3 * values["thirdHarmonicA"]
    total = math.hypot(values["fundamentalNeutralA"], values["unbalanceA"]) + harmonic_neutral
    return result(
        summary={
            "estimatedNeutralCurrentA": total,
            "ampacityMarginA": values["neutralAmpacityA"] - total,
            "passes": total <= values["neutralAmpacityA"],
        },
        notes=[
            "Triplen third-harmonic currents from three phases are conservatively added in the neutral; detailed harmonic phasors and thermal derating are not modeled."
        ],
    )


@feature(
    "mepElectrical.demandFactor",
    "Demand Factor",
    part="mep",
    fields=[
        number("connectedLoadKw", "Connected load", 120, unit="kW", min=0),
        number("demandFactor", "Demand factor", 0.7, min=0, max=1),
        number("powerFactor", "Power factor", 0.9, min=0.1, max=1),
    ],
    requires_project=False,
)
def demand_factor(ctx: FeatureContext, values: dict) -> dict:
    """Apply the board demand factor and calculate apparent demand."""
    demand = values["connectedLoadKw"] * values["demandFactor"]
    return result(
        summary={
            "maximumDemandKw": demand,
            "apparentDemandKva": demand / values["powerFactor"],
            "demandFactor": values["demandFactor"],
        },
        notes=[
            "Demand factor is an explicit project input; use applicable load schedules and operating profiles to justify it."
        ],
    )


@feature("mepElectrical.connectedLoad", "Connected Load", part="mep", requires_project=True)
def connected_load(ctx: FeatureContext, values: dict) -> dict:
    """Sum project electrical loads recorded as circuit or load entries."""
    electrical = _electrical(ctx)
    loads = electrical.get("loads", electrical.get("circuits", []))
    if not loads:
        raise FeatureInputError(
            "Add electrical load or circuit entries before totaling connected load."
        )
    rows = [
        {
            "id": row.get("id", ""),
            "board": row.get("board", ""),
            "loadKw": float(row.get("loadKw", row.get("ratingKw", 0))),
        }
        for row in loads
    ]
    return result(
        summary={
            "connectedLoadKw": sum(row["loadKw"] for row in rows),
            "loadEntryCount": len(rows),
        },
        tables=[
            table(
                "Connected electrical loads",
                [("id", "Circuit or load"), ("board", "Board"), ("loadKw", "Connected load", "kW")],
                rows,
            )
        ],
        notes=[
            "Only explicit project load and circuit entries are summed; transformer and generator equipment ratings are not treated as demand."
        ],
    )


@feature(
    "mepElectrical.diversityLoad",
    "Diversity Load",
    part="mep",
    fields=[
        number("lightingLoadKw", "Lighting load", 30, unit="kW", min=0),
        number("powerLoadKw", "Small power load", 45, unit="kW", min=0),
        number("hvacLoadKw", "HVAC electrical load", 60, unit="kW", min=0),
        number("essentialLoadKw", "Essential load", 15, unit="kW", min=0),
        number("generalDiversity", "General load factor", 0.7, min=0, max=1),
        number("hvacDiversity", "HVAC coincidence", 0.9, min=0, max=1),
    ],
    requires_project=False,
)
def diversity_load(ctx: FeatureContext, values: dict) -> dict:
    """Estimate diversified demand by end-use group."""
    general = (values["lightingLoadKw"] + values["powerLoadKw"]) * values["generalDiversity"]
    hvac = values["hvacLoadKw"] * values["hvacDiversity"]
    total = general + hvac + values["essentialLoadKw"]
    return result(
        summary={
            "generalDemandKw": general,
            "hvacDemandKw": hvac,
            "essentialDemandKw": values["essentialLoadKw"],
            "diversifiedDemandKw": total,
        },
        notes=[
            "Essential demand is added without diversity; the entered group factors represent project coincidence assumptions."
        ],
    )


@feature(
    "mepElectrical.powerFactor",
    "Power Factor",
    part="mep",
    fields=[
        number("activePowerKw", "Active power", 100, unit="kW", min=0),
        number("existingPowerFactor", "Existing power factor", 0.82, min=0.1, max=1),
        number("targetPowerFactor", "Target power factor", 0.95, min=0.1, max=1),
    ],
    requires_project=False,
)
def power_factor(ctx: FeatureContext, values: dict) -> dict:
    """Calculate capacitor reactive power needed to improve power factor."""
    p = values["activePowerKw"]
    old_angle = math.acos(values["existingPowerFactor"])
    target_angle = math.acos(values["targetPowerFactor"])
    kvar = p * (math.tan(old_angle) - math.tan(target_angle))
    return result(
        summary={
            "compensationKvar": max(kvar, 0),
            "initialApparentKva": p / values["existingPowerFactor"],
            "targetApparentKva": p / values["targetPowerFactor"],
        },
        notes=[
            "Required capacitor rating uses Qc = P(tan φ₁ − tan φ₂); assess harmonic resonance, step control and utility requirements."
        ],
    )


@feature("mepElectrical.electricalLegend", "Electrical Legend", part="mep", requires_project=True)
def electrical_legend(ctx: FeatureContext, values: dict) -> dict:
    """Build a symbol legend from modeled electrical equipment and distribution items."""
    electrical = _electrical(ctx)
    records = (
        electrical.get("equipment", []) + electrical.get("risers", []) + electrical.get("trays", [])
    )
    if not records:
        raise FeatureInputError(
            "Add electrical equipment, risers or containment before preparing the legend."
        )
    kinds = {}
    for row in records:
        kind = str(row.get("kind", row.get("system", "unspecified")))
        kinds[kind] = kinds.get(kind, 0) + 1
    rows = [
        {"symbol": kind, "description": kind.replace("_", " ").title(), "count": count}
        for kind, count in sorted(kinds.items())
    ]
    return result(
        summary={"legendEntryCount": len(rows)},
        tables=[
            table(
                "Electrical drawing legend",
                [("symbol", "Symbol key"), ("description", "Description"), ("count", "Instances")],
                rows,
            )
        ],
        notes=[
            "Legend entries are derived from equipment and system type fields available in the project model."
        ],
    )


@feature("mepElectrical.oneLineDiagram", "One-Line Diagram", part="mep", requires_project=True)
def one_line_diagram(ctx: FeatureContext, values: dict) -> dict:
    """Prepare one-line nodes and links from electrical equipment and risers."""
    electrical = _electrical(ctx)
    supply = electrical.get("supply", {})
    nodes = [
        {
            "node": "Incoming supply",
            "type": "utility",
            "rating": supply.get("voltage", "unspecified"),
        }
    ]
    nodes.extend(
        {
            "node": item.get("id", ""),
            "type": item.get("kind", "equipment"),
            "rating": item.get("rating", ""),
        }
        for item in electrical.get("equipment", [])
    )
    nodes.extend(
        {
            "node": item.get("id", ""),
            "type": item.get("kind", "riser"),
            "rating": item.get("width", ""),
        }
        for item in electrical.get("risers", [])
    )
    if len(nodes) == 1:
        raise FeatureInputError(
            "Add electrical distribution equipment or risers to create a one-line diagram."
        )
    edges = [
        {"sequence": i, "from": nodes[i]["node"], "to": nodes[i + 1]["node"]}
        for i in range(len(nodes) - 1)
    ]
    return result(
        summary={
            "diagramNodeCount": len(nodes),
            "diagramLinkCount": len(edges),
            "supplyVoltage": supply.get("voltage", "unspecified"),
        },
        tables=[
            table(
                "One-line nodes",
                [("node", "Node"), ("type", "Equipment type"), ("rating", "Rating")],
                nodes,
            ),
            table(
                "Diagram links", [("sequence", "Sequence"), ("from", "From"), ("to", "To")], edges
            ),
        ],
        notes=[
            "This sequence diagram data follows project record order; electrical connectivity must be confirmed from explicit board, feeder and circuit topology."
        ],
    )


@feature(
    "mepElectrical.electricalNotes",
    "Electrical Notes",
    part="mep",
    fields=[
        select("systemVoltage", "System voltage", ["230/400 V", "208/120 V", "480/277 V"]),
        number("frequencyHz", "System frequency", 50, unit="Hz", min=1),
        number("designAmbientC", "Electrical room design ambient", 35, unit="°C"),
        text("earthingArrangement", "Earthing arrangement", "TN-S"),
    ],
    requires_project=False,
)
def electrical_notes(ctx: FeatureContext, values: dict) -> dict:
    """Prepare project-specific electrical installation notes."""
    notes = [
        {"topic": "Supply", "note": f"{values['systemVoltage']}, {values['frequencyHz']} Hz"},
        {"topic": "Environment", "note": f"Design ambient {values['designAmbientC']} °C"},
        {"topic": "Earthing", "note": values["earthingArrangement"]},
        {
            "topic": "Verification",
            "note": "Verify protective-device coordination, fault level, earthing continuity and voltage drop against final design.",
        },
    ]
    return result(
        summary={"noteCount": len(notes)},
        tables=[table("Electrical design notes", [("topic", "Topic"), ("note", "Note")], notes)],
        notes=["Notes are generated from the entered project system basis."],
    )


@feature("mepElectrical.circuitTags", "Circuit Tags", part="mep", requires_project=True)
def circuit_tags(ctx: FeatureContext, values: dict) -> dict:
    """Prepare circuit plan tags from electrical circuit records."""
    electrical = _electrical(ctx)
    circuits = electrical.get("circuits", [])
    if not circuits:
        raise FeatureInputError(
            "Add electrical circuit records with board and way references first."
        )
    tags = [
        {
            "circuit": c.get("id", ""),
            "tag": f"{c.get('board', '?')}-{c.get('way', '?')}",
            "loadKw": c.get("loadKw", c.get("ratingKw", "")),
        }
        for c in circuits
    ]
    return result(
        summary={"tagCount": len(tags)},
        tables=[
            table(
                "Circuit tags",
                [("circuit", "Circuit"), ("tag", "Plan tag"), ("loadKw", "Load", "kW")],
                tags,
            )
        ],
        notes=[
            "Tags combine the circuit board and way fields; missing references are marked with '?'."
        ],
    )
