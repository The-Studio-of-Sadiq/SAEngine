"""MEP remaining view, coordination, fixture and duct features."""

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
    "mepViews.ceilingPlanView",
    "Ceiling Plan View",
    part="mep",
    fields=[text("level", "Level", "")],
    requires_project=True,
)
def ceiling_plan_view(ctx, v):
    raw = ctx.raw("mep") or {}
    return result(
        summary={"level": v["level"], "equipment": len(raw.get("equipment", []))},
        tables=[
            table(
                "Ceiling plan",
                [("level", "Level"), ("equipment", "Equipment")],
                [{"level": v["level"], "equipment": len(raw.get("equipment", []))}],
            )
        ],
        notes=["Ceiling-plan inventory from the MEP model."],
    )


@feature(
    "mepViews.detailView",
    "Detail View",
    part="mep",
    fields=[
        text("detail", "Detail name", "MEP detail"),
        number("scale", "Scale", 50, unit="mm/m", min=1),
    ],
    requires_project=False,
)
def detail_view(ctx, v):
    return result(
        summary={"detail": v["detail"], "scaleMmPerM": v["scale"]},
        tables=[
            table(
                "Detail",
                [("detail", "Detail"), ("scale", "Scale", "mm/m")],
                [{"detail": v["detail"], "scale": v["scale"]}],
            )
        ],
        notes=["Detail view scale and name."],
    )


@feature(
    "mepViews.viewRange",
    "View Range",
    part="mep",
    fields=[
        number("bottom", "Bottom level", 0, unit="mm"),
        number("top", "Top level", 3000, unit="mm"),
    ],
    requires_project=False,
)
def view_range(ctx, v):
    return result(
        summary={"bottomMm": v["bottom"], "topMm": v["top"], "heightMm": v["top"] - v["bottom"]},
        tables=[
            table(
                "View range",
                [("level", "Level"), ("value", "Value", "mm")],
                [{"level": "Bottom", "value": v["bottom"]}, {"level": "Top", "value": v["top"]}],
            )
        ],
        notes=["Vertical view clipping range."],
    )


@feature(
    "mepViews.viewTemplate",
    "View Template",
    part="mep",
    fields=[
        text("template", "Template name", "Coordination"),
        checkbox("hiddenLines", "Hidden lines", True),
    ],
    requires_project=False,
)
def view_template(ctx, v):
    return result(
        summary={"template": v["template"], "hiddenLines": v["hiddenLines"]},
        tables=[
            table(
                "View template",
                [("setting", "Setting"), ("value", "Value")],
                [
                    {"setting": "Name", "value": v["template"]},
                    {"setting": "Hidden lines", "value": v["hiddenLines"]},
                ],
            )
        ],
        notes=["Named presentation template state."],
    )


@feature(
    "mepViews.worksetFilter",
    "Workset Filter",
    part="mep",
    fields=[text("workset", "Workset", "All")],
    requires_project=False,
)
def workset_filter(ctx, v):
    return result(
        summary={"workset": v["workset"]},
        tables=[table("Workset filter", [("workset", "Workset")], [{"workset": v["workset"]}])],
        notes=["Workset filter state for linked models."],
    )


@feature(
    "mepViews.phaseFilter",
    "Phase Filter",
    part="mep",
    fields=[text("phase", "Phase", "Current")],
    requires_project=False,
)
def phase_filter(ctx, v):
    return result(
        summary={"phase": v["phase"]},
        tables=[table("Phase filter", [("phase", "Phase")], [{"phase": v["phase"]}])],
        notes=["Phase filter state."],
    )


@feature(
    "mepViews.categoryOverride",
    "Category Override",
    part="mep",
    fields=[
        text("category", "Category", "HVAC"),
        select(
            "line",
            "Line style",
            [("thin", "Thin"), ("medium", "Medium"), ("bold", "Bold")],
            "medium",
        ),
    ],
    requires_project=False,
)
def category_override(ctx, v):
    return result(
        summary={"category": v["category"], "line": v["line"]},
        tables=[
            table(
                "Category override",
                [("category", "Category"), ("line", "Line")],
                [{"category": v["category"], "line": v["line"]}],
            )
        ],
        notes=["Category presentation override."],
    )


@feature(
    "mepViews.hideUnassigned",
    "Hide Unassigned",
    part="mep",
    fields=[checkbox("hide", "Hide unassigned", True)],
    requires_project=True,
)
def hide_unassigned(ctx, v):
    raw = ctx.raw("mep") or {}
    return result(
        summary={"hide": v["hide"], "equipment": len(raw.get("equipment", []))},
        tables=[
            table(
                "Unassigned filter",
                [("setting", "Setting"), ("value", "Value")],
                [{"setting": "Hide unassigned", "value": v["hide"]}],
            )
        ],
        notes=["Presentation filter; assignment values remain in the model."],
    )


@feature(
    "mepViews.revealHiddenItems",
    "Reveal Hidden Items",
    part="mep",
    fields=[
        checkbox("services", "Reveal services", True),
        checkbox("clashes", "Reveal clashes", True),
    ],
    requires_project=False,
)
def reveal_hidden_items(ctx, v):
    return result(
        summary={"services": v["services"], "clashes": v["clashes"]},
        tables=[
            table(
                "Reveal hidden",
                [("item", "Item"), ("visible", "Visible")],
                [
                    {"item": "Services", "visible": v["services"]},
                    {"item": "Clashes", "visible": v["clashes"]},
                ],
            )
        ],
        notes=["Temporary display-state operation."],
    )


@feature(
    "mepViews.savedViewpoints",
    "Saved Viewpoints",
    part="mep",
    fields=[text("name", "Viewpoint name", "Coordination")],
    requires_project=True,
)
def saved_viewpoints(ctx, v):
    return result(
        summary={"viewpoint": v["name"]},
        tables=[table("Saved viewpoints", [("name", "Name")], [{"name": v["name"]}])],
        notes=["Viewpoint state can be attached to coordination issues."],
    )


@feature(
    "mepViews.viewHistory",
    "View History",
    part="mep",
    fields=[number("limit", "History entries", 20, unit="entries", min=1, max=100)],
    requires_project=False,
)
def view_history(ctx, v):
    return result(
        summary={"limit": int(v["limit"])},
        tables=[table("View history", [("limit", "Limit", "entries")], [{"limit": v["limit"]}])],
        notes=["Limit for model-review history."],
    )


@feature(
    "mepViews.walkToView",
    "Walk To View",
    part="mep",
    fields=[
        number("x", "X", 0, unit="mm"),
        number("y", "Y", 0, unit="mm"),
        number("z", "Z", 1700, unit="mm"),
    ],
    requires_project=False,
)
def walk_to_view(ctx, v):
    return result(
        summary={"xMm": v["x"], "yMm": v["y"], "zMm": v["z"]},
        tables=[
            table(
                "Walk viewpoint",
                [("axis", "Axis"), ("value", "Value", "mm")],
                [
                    {"axis": "X", "value": v["x"]},
                    {"axis": "Y", "value": v["y"]},
                    {"axis": "Z", "value": v["z"]},
                ],
            )
        ],
        notes=["Camera target for a first-person coordination review."],
    )


@feature(
    "mepViews.zoomToClash",
    "Zoom To Clash",
    part="mep",
    fields=[text("clash", "Clash id", "")],
    requires_project=True,
)
def zoom_to_clash(ctx, v):
    if not v["clash"]:
        raise FeatureInputError("Enter a clash id.")
    return result(
        summary={"clash": v["clash"]},
        tables=[table("Clash viewpoint", [("clash", "Clash")], [{"clash": v["clash"]}])],
        notes=["Selects the issue location in the view."],
    )


@feature(
    "mepViews.clipDepth",
    "Clip Depth",
    part="mep",
    fields=[number("depth", "Clip depth", 3000, unit="mm", min=1)],
    requires_project=False,
)
def clip_depth(ctx, v):
    return result(
        summary={"depthMm": v["depth"]},
        tables=[table("Clip depth", [("depth", "Depth", "mm")], [{"depth": v["depth"]}])],
        notes=["Depth of the active section/clip plane."],
    )
