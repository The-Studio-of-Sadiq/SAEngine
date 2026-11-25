"""MEP coordination view and presentation features."""

from saengine.features import (
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)


@feature(
    "mepViews.sectionCut",
    "Section Cut",
    part="mep",
    fields=[
        number("x", "Section X", 0, unit="mm"),
        number("y", "Section Y", 0, unit="mm"),
        number("z", "Section Z", 3000, unit="mm"),
    ],
    requires_project=False,
)
def section_cut(ctx, v):
    return result(
        summary={"pointXmm": v["x"], "pointYmm": v["y"], "pointZmm": v["z"]},
        tables=[
            table(
                "Section cut",
                [("axis", "Axis"), ("position", "Position", "mm")],
                [
                    {"axis": "X", "position": v["x"]},
                    {"axis": "Y", "position": v["y"]},
                    {"axis": "Z", "position": v["z"]},
                ],
            )
        ],
        notes=["Three-dimensional section position for the coordination viewer."],
    )


@feature(
    "mepViews.clipBox",
    "Clip Box",
    part="mep",
    fields=[
        number("xmin", "Minimum X", 0, unit="mm"),
        number("xmax", "Maximum X", 10000, unit="mm"),
        number("ymin", "Minimum Y", 0, unit="mm"),
        number("ymax", "Maximum Y", 10000, unit="mm"),
    ],
    requires_project=False,
)
def clip_box(ctx, v):
    w = v["xmax"] - v["xmin"]
    h = v["ymax"] - v["ymin"]
    if w < 0 or h < 0:
        raise ValueError("Clip bounds must form a positive rectangle.")
    return result(
        summary={"widthMm": w, "depthMm": h, "areaM2": w * h / 1e6},
        tables=[
            table(
                "Clip box",
                [("bound", "Bound"), ("value", "Value", "mm")],
                [
                    {"bound": "X minimum", "value": v["xmin"]},
                    {"bound": "X maximum", "value": v["xmax"]},
                    {"bound": "Y minimum", "value": v["ymin"]},
                    {"bound": "Y maximum", "value": v["ymax"]},
                ],
            )
        ],
        notes=["The clip box is a rectangular plan envelope."],
    )


@feature(
    "mepViews.elevationView",
    "Elevation View",
    part="mep",
    fields=[
        select(
            "direction",
            "Direction",
            [("north", "North"), ("south", "South"), ("east", "East"), ("west", "West")],
            "north",
        ),
        number("elevation", "View elevation", 3000, unit="mm", min=0),
    ],
    requires_project=False,
)
def elevation_view(ctx, v):
    return result(
        summary={"direction": v["direction"], "elevationMm": v["elevation"]},
        tables=[
            table(
                "Elevation view",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Direction", "value": v["direction"]},
                    {"property": "Elevation", "value": v["elevation"]},
                ],
            )
        ],
        notes=["Elevation camera view state."],
    )


@feature(
    "mepViews.disciplineFilters",
    "Discipline Filters",
    part="mep",
    fields=[
        checkbox("mechanical", "Mechanical", True),
        checkbox("plumbing", "Plumbing", True),
        checkbox("electrical", "Electrical", True),
        checkbox("fire", "Fire", True),
    ],
    requires_project=False,
)
def discipline_filters(ctx, v):
    rows = [
        {"discipline": "Mechanical", "visible": v["mechanical"]},
        {"discipline": "Plumbing", "visible": v["plumbing"]},
        {"discipline": "Electrical", "visible": v["electrical"]},
        {"discipline": "Fire", "visible": v["fire"]},
    ]
    return result(
        summary={"visibleDisciplines": sum(r["visible"] for r in rows)},
        tables=[
            table(
                "Discipline filters", [("discipline", "Discipline"), ("visible", "Visible")], rows
            )
        ],
        notes=["Controls discipline visibility in the coordination view."],
    )


@feature(
    "mepViews.transparency",
    "Transparency",
    part="mep",
    fields=[number("percent", "Transparency", 30, unit="%", min=0, max=100)],
    requires_project=False,
)
def transparency(ctx, v):
    return result(
        summary={"transparencyPercent": v["percent"], "opacityPercent": 100 - v["percent"]},
        tables=[
            table(
                "Transparency",
                [("setting", "Setting"), ("percent", "Percent", "%")],
                [
                    {"setting": "Transparency", "percent": v["percent"]},
                    {"setting": "Opacity", "percent": 100 - v["percent"]},
                ],
            )
        ],
        notes=["Presentation alpha state only."],
    )


@feature(
    "mepViews.hatchOverride",
    "Hatch Override",
    part="mep",
    fields=[
        text("pattern", "Hatch pattern", "Diagonal"),
        select(
            "discipline",
            "Discipline",
            [
                ("mechanical", "Mechanical"),
                ("plumbing", "Plumbing"),
                ("electrical", "Electrical"),
                ("fire", "Fire"),
            ],
            "mechanical",
        ),
    ],
    requires_project=False,
)
def hatch_override(ctx, v):
    return result(
        summary={"discipline": v["discipline"], "pattern": v["pattern"]},
        tables=[
            table(
                "Hatch override",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Discipline", "value": v["discipline"]},
                    {"property": "Pattern", "value": v["pattern"]},
                ],
            )
        ],
        notes=["Presentation hatch override for plans."],
    )


@feature(
    "mepViews.compareRevisions",
    "Compare Revisions",
    part="mep",
    fields=[text("a", "Revision A", "A"), text("b", "Revision B", "B")],
    requires_project=True,
)
def compare_revisions(ctx, v):
    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add 07 MEP/mep.json to the project.")
    return result(
        summary={
            "revisionA": v["a"],
            "revisionB": v["b"],
            "currentEquipment": len(raw.get("equipment", [])),
        },
        tables=[
            table(
                "Revision comparison",
                [("revision", "Revision"), ("equipment", "Equipment")],
                [
                    {"revision": v["a"], "equipment": 0},
                    {"revision": v["b"], "equipment": len(raw.get("equipment", []))},
                ],
            )
        ],
        notes=["Compare archived revisions by separate snapshot data."],
    )


@feature(
    "mepViews.snapshot",
    "Snapshot",
    part="mep",
    fields=[text("name", "Snapshot name", "MEP view")],
    requires_project=True,
)
def snapshot(ctx, v):
    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add 07 MEP/mep.json to the project.")
    return result(
        summary={
            "name": v["name"],
            "equipment": len(raw.get("equipment", [])),
            "openings": len(raw.get("openings", [])),
        },
        tables=[
            table(
                "View snapshot",
                [("item", "Item"), ("count", "Count")],
                [
                    {"item": "Equipment", "count": len(raw.get("equipment", []))},
                    {"item": "Openings", "count": len(raw.get("openings", []))},
                ],
            )
        ],
        notes=["View snapshot inventory; render capture is handled by the workbench."],
    )


@feature(
    "mepViews.markup",
    "Markup",
    part="mep",
    fields=[text("author", "Author", ""), text("text", "Markup text", "Review required")],
    requires_project=False,
)
def markup(ctx, v):
    if not v["text"]:
        raise ValueError("Enter markup text.")
    return result(
        summary={"author": v["author"], "markup": v["text"]},
        tables=[
            table(
                "Markup",
                [("field", "Field"), ("value", "Value")],
                [{"field": "Author", "value": v["author"]}, {"field": "Text", "value": v["text"]}],
            )
        ],
        notes=["Markup text is ready for redline attachment."],
    )


@feature(
    "mepViews.floorPlanView",
    "Floor Plan View",
    part="mep",
    fields=[text("level", "Level id", "")],
    requires_project=True,
)
def floor_plan_view(ctx, v):
    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add 07 MEP/mep.json to the project.")
    equipment = [
        e for e in raw.get("equipment", []) if not v["level"] or e.get("story") == v["level"]
    ]
    return result(
        summary={"level": v["level"], "equipment": len(equipment)},
        tables=[
            table(
                "Floor-plan content",
                [("id", "Equipment"), ("x", "X", "mm"), ("y", "Y", "mm")],
                [
                    {"id": e.get("id", ""), "x": e.get("x", 0), "y": e.get("y", 0)}
                    for e in equipment
                ],
            )
        ],
        notes=["Floor-plan coordinates are from 07 MEP equipment entries."],
    )
