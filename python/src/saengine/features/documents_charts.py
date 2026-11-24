"""Worksheet chart construction, analysis and SVG export."""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    text,
)
from saengine.features.documents_common import (
    cell_value,
    range_cells,
    require_root,
    save_worksheet_workspace,
    worksheet_workspace,
)


def _open(ctx, values):
    return worksheet_workspace(ctx, values["worksheetId"])


def _save(ctx, sheet, state, summary):
    path = save_worksheet_workspace(ctx, sheet, state)
    return result(summary={**summary, "worksheetId": sheet.id, "worksheetPath": path})


def _rows(ctx, values, x_range, y_range):
    sheet, state = _open(ctx, values)
    xs = [cell_value(a, state) for a in range_cells(x_range)]
    ys = [cell_value(a, state) for a in range_cells(y_range)]
    if len(xs) != len(ys) or not xs:
        raise FeatureInputError(
            "Chart x and y ranges must contain the same non-zero number of cells."
        )
    return sheet, state, list(zip(xs, ys))


def _chart(state, chart_id):
    chart = next(
        (item for item in state.setdefault("charts", []) if item.get("id") == chart_id), None
    )
    if chart is None:
        raise FeatureInputError(f"Chart {chart_id!r} does not exist; create a chart first.")
    return chart


def _new(state, chart_id, kind, title, series):
    charts = state.setdefault("charts", [])
    charts[:] = [c for c in charts if c.get("id") != chart_id]
    chart = {
        "id": chart_id,
        "type": kind,
        "title": title,
        "series": [series],
        "axes": {"x": {"title": "X"}, "y": {"title": "Y"}},
        "legend": {"show": True},
        "gridlines": {"x": True, "y": True},
        "style": {},
    }
    charts.append(chart)
    return chart


def _range_series(name, xs, ys):
    return {
        "name": name,
        "points": [{"x": x, "y": y} for x, y in zip(xs, ys, strict=True)],
        "axis": "primary",
    }


@feature(
    "docCharts.lineChart",
    "Line Chart",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("title", "Chart title", "Load response"),
        text("xRange", "X range", "A1:A10"),
        text("yRange", "Y range", "B1:B10"),
    ],
)
def line_chart(ctx: FeatureContext, values: dict) -> dict:
    """Create a line chart from two equal-length numeric worksheet ranges."""
    sheet, state, points = _rows(ctx, values, values["xRange"], values["yRange"])
    chart = _new(
        state,
        values["chartId"],
        "line",
        values["title"],
        _range_series("Series 1", [p[0] for p in points], [p[1] for p in points]),
    )
    return _save(
        ctx, sheet, state, {"chartId": chart["id"], "pointCount": len(points), "chartType": "line"}
    )


@feature(
    "docCharts.barChart",
    "Bar Chart",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("title", "Chart title", "Member quantities"),
        text("categoryRange", "Category range", "A1:A5"),
        text("valueRange", "Value range", "B1:B5"),
        select(
            "orientation",
            "Bars",
            [("vertical", "Vertical"), ("horizontal", "Horizontal")],
            "vertical",
        ),
    ],
)
def bar_chart(ctx: FeatureContext, values: dict) -> dict:
    """Create a categorical bar chart with validated category and numeric value ranges."""
    sheet, state, points = _rows(ctx, values, values["categoryRange"], values["valueRange"])
    chart = _new(
        state,
        values["chartId"],
        "bar",
        values["title"],
        _range_series("Series 1", [p[0] for p in points], [p[1] for p in points]),
    )
    chart["orientation"] = values["orientation"]
    return _save(
        ctx,
        sheet,
        state,
        {"chartId": chart["id"], "barCount": len(points), "orientation": values["orientation"]},
    )


@feature(
    "docCharts.scatter",
    "Scatter Chart",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("title", "Chart title", "Load-deflection response"),
        text("xRange", "X values", "A1:A10"),
        text("yRange", "Y values", "B1:B10"),
    ],
)
def scatter(ctx: FeatureContext, values: dict) -> dict:
    """Create an x-y scatter chart with unconnected measured or calculated data points."""
    sheet, state, points = _rows(ctx, values, values["xRange"], values["yRange"])
    chart = _new(
        state,
        values["chartId"],
        "scatter",
        values["title"],
        _range_series("Series 1", [p[0] for p in points], [p[1] for p in points]),
    )
    return _save(ctx, sheet, state, {"chartId": chart["id"], "pointCount": len(points)})


@feature(
    "docCharts.contourPlot",
    "Contour Plot",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("title", "Plot title", "Plate response contours"),
        text("xRange", "X coordinates", "A1:A10"),
        text("yRange", "Y coordinates", "B1:B10"),
        text("valueRange", "Contour values", "C1:C10"),
        number("levels", "Contour levels", 10, min=2, max=50),
    ],
)
def contour_plot(ctx: FeatureContext, values: dict) -> dict:
    """Create a contour data plot and calculate evenly spaced contour levels from real worksheet values."""
    sheet, state, xy = _rows(ctx, values, values["xRange"], values["yRange"])
    zs = [cell_value(a, state) for a in range_cells(values["valueRange"])]
    if len(zs) != len(xy):
        raise FeatureInputError("X, Y and contour value ranges must have matching lengths.")
    lo, hi = min(zs), max(zs)
    levels = [
        lo + (hi - lo) * i / (int(values["levels"]) - 1) for i in range(int(values["levels"]))
    ]
    chart = _new(
        state,
        values["chartId"],
        "contour",
        values["title"],
        _range_series("Response", [p[0] for p in xy], zs),
    )
    chart["points"] = [{"x": x, "y": y, "value": z} for (x, y), z in zip(xy, zs, strict=True)]
    chart["contourLevels"] = levels
    return _save(
        ctx, sheet, state, {"chartId": chart["id"], "pointCount": len(zs), "contourLevels": levels}
    )


@feature(
    "docCharts.surfaceChart",
    "Surface Chart",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("title", "Surface title", "Capacity surface"),
        text("xRange", "X coordinates", "A1:A9"),
        text("yRange", "Y coordinates", "B1:B9"),
        text("zRange", "Surface response", "C1:C9"),
    ],
)
def surface_chart(ctx: FeatureContext, values: dict) -> dict:
    """Store real x-y-z grid samples for a three-dimensional worksheet surface plot."""
    sheet, state, xy = _rows(ctx, values, values["xRange"], values["yRange"])
    zs = [cell_value(a, state) for a in range_cells(values["zRange"])]
    if len(zs) != len(xy):
        raise FeatureInputError("X, Y and Z ranges must contain matching points.")
    chart = _new(
        state,
        values["chartId"],
        "surface",
        values["title"],
        _range_series("Surface", [p[0] for p in xy], zs),
    )
    chart["points"] = [{"x": x, "y": y, "z": z} for (x, y), z in zip(xy, zs, strict=True)]
    return _save(ctx, sheet, state, {"chartId": chart["id"], "gridPointCount": len(zs)})


@feature(
    "docCharts.axisSettings",
    "Axis Settings",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        select("axis", "Axis", [("x", "Horizontal"), ("y", "Vertical")], "y"),
        text("title", "Axis title", "Utilization"),
        number("minimum", "Minimum", 0),
        number("maximum", "Maximum", 1),
        number("majorStep", "Major step", 0.2, min=0.000001),
    ],
)
def axis_settings(ctx: FeatureContext, values: dict) -> dict:
    """Set chart-axis title, numeric bounds and major tick interval."""
    if values["minimum"] >= values["maximum"]:
        raise FeatureInputError("Axis minimum must be less than maximum.")
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    chart.setdefault("axes", {})[values["axis"]] = {
        "title": values["title"],
        "minimum": values["minimum"],
        "maximum": values["maximum"],
        "majorStep": values["majorStep"],
    }
    return _save(
        ctx,
        sheet,
        state,
        {
            "chartId": chart["id"],
            "axis": values["axis"],
            "bounds": [values["minimum"], values["maximum"]],
        },
    )


@feature(
    "docCharts.chartLegend",
    "Chart Legend",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        checkbox("show", "Show legend", True),
        select(
            "position",
            "Position",
            [("top", "Top"), ("bottom", "Bottom"), ("left", "Left"), ("right", "Right")],
            "right",
        ),
    ],
)
def chart_legend(ctx: FeatureContext, values: dict) -> dict:
    """Show or hide a chart legend and choose its placement."""
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    chart["legend"] = {"show": values["show"], "position": values["position"]}
    return _save(
        ctx, sheet, state, {"legendVisible": values["show"], "position": values["position"]}
    )


@feature(
    "docCharts.dataLabels",
    "Data Labels",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        checkbox("show", "Show labels", True),
        select(
            "content",
            "Label content",
            [("value", "Value"), ("category", "Category"), ("both", "Category and value")],
            "value",
        ),
        number("precision", "Decimal places", 2, min=0, max=8),
    ],
)
def data_labels(ctx: FeatureContext, values: dict) -> dict:
    """Configure chart data labels and materialize display strings for each point."""
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    precision = int(values["precision"])
    for series in chart["series"]:
        for point in series["points"]:
            point["label"] = (
                (str(point["x"]) + " : " if values["content"] in ("category", "both") else "")
                + (
                    (
                        f"{point['y']:.{precision}f}"
                        if isinstance(point["y"], (int, float))
                        else str(point["y"])
                    )
                    if values["content"] in ("value", "both")
                    else ""
                )
                if values["show"]
                else None
            )
    chart["dataLabels"] = {
        "show": values["show"],
        "content": values["content"],
        "precision": precision,
    }
    return _save(
        ctx,
        sheet,
        state,
        {
            "chartId": chart["id"],
            "labelledPoints": sum(len(s["points"]) for s in chart["series"])
            if values["show"]
            else 0,
        },
    )


@feature(
    "docCharts.exportChartImage",
    "Export Chart Image",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("svgPath", "Project-relative SVG path", "11 Exports/charts/chart-1.svg"),
        number("widthPx", "Image width", 1000, min=100, max=5000),
        number("heightPx", "Image height", 600, min=100, max=5000),
    ],
)
def export_chart_image(ctx: FeatureContext, values: dict) -> dict:
    """Render a stored chart and its numerical series as a standalone vector SVG image."""
    root = require_root(ctx)
    target = (root / values["svgPath"]).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("SVG output must stay inside the project folder.") from exc
    _sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    points = [
        p
        for series in chart["series"]
        for p in series["points"]
        if isinstance(p.get("x"), (int, float)) and isinstance(p.get("y"), (int, float))
    ]
    if not points:
        raise FeatureInputError("Chart has no numeric points to render.")
    w, h = int(values["widthPx"]), int(values["heightPx"])
    left, top, right, bottom = 70, 55, w - 30, h - 70
    xs = [p["x"] for p in points]
    ys = [p["y"] for p in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    xspan = xmax - xmin or 1
    yspan = ymax - ymin or 1

    def px(x):
        return left + (x - xmin) / xspan * (right - left)

    def py(y):
        return bottom - (y - ymin) / yspan * (bottom - top)

    colour_cycle = ("#4472C4", "#ED7D31", "#70AD47", "#A5A5A5", "#8064A2")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="white"/><text x="{w / 2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="18">{escape(chart["title"])}</text>'
    ]
    if chart.get("gridlines", {}).get("y", True):
        for i in range(6):
            y = top + (bottom - top) * i / 5
            value = ymax - yspan * i / 5
            parts.append(
                f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#DDDDDD"/><text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-family="sans-serif" font-size="11">{value:.3g}</text>'
            )
    parts.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#333"/>',
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#333"/>',
        ]
    )
    for si, series in enumerate(chart["series"]):
        pts = [
            p
            for p in series["points"]
            if isinstance(p.get("x"), (int, float)) and isinstance(p.get("y"), (int, float))
        ]
        color = series.get("colour", colour_cycle[si % len(colour_cycle)])
        if chart["type"] in (
            "line",
            "scatter",
            "contour",
            "surface",
            "interaction",
            "stress",
            "envelope",
        ):
            coords = " ".join(f"{px(p['x']):.2f},{py(p['y']):.2f}" for p in pts)
            if chart["type"] in ("line", "contour", "surface", "interaction", "stress", "envelope"):
                parts.append(
                    f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{coords}"/>'
                )
            parts.extend(
                f'<circle cx="{px(p["x"]):.2f}" cy="{py(p["y"]):.2f}" r="3" fill="{color}"/>'
                for p in pts
            )
        elif chart["type"] in ("bar", "waterfall"):
            step = (right - left) / max(1, len(pts))
            base = py(0 if ymin <= 0 <= ymax else ymin)
            for i, p in enumerate(pts):
                parts.append(
                    f'<rect x="{left + i * step + step * 0.12:.2f}" y="{min(py(p["y"]), base):.2f}" width="{step * 0.76:.2f}" height="{abs(base - py(p["y"])):.2f}" fill="{color}"/>'
                )
    parts.append(
        f'<text x="{(left + right) / 2}" y="{h - 18}" text-anchor="middle" font-family="sans-serif" font-size="12">{escape(chart.get("axes", {}).get("x", {}).get("title", "X"))}</text><text x="18" y="{(top + bottom) / 2}" transform="rotate(-90 18 {(top + bottom) / 2})" text-anchor="middle" font-family="sans-serif" font-size="12">{escape(chart.get("axes", {}).get("y", {}).get("title", "Y"))}</text></svg>'
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(parts), encoding="utf-8")
    return result(
        summary={
            "chartId": chart["id"],
            "svgPath": target.relative_to(root).as_posix(),
            "widthPx": w,
            "heightPx": h,
            "pointCount": len(points),
        }
    )


@feature(
    "docCharts.copyChart",
    "Copy Chart",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("sourceChartId", "Source chart id", "chart-1"),
        text("newChartId", "New chart id", "chart-copy"),
    ],
)
def copy_chart(ctx: FeatureContext, values: dict) -> dict:
    """Duplicate a chart definition and its series under a new worksheet chart identifier."""
    import copy

    sheet, state = _open(ctx, values)
    source = _chart(state, values["sourceChartId"])
    if any(c.get("id") == values["newChartId"] for c in state["charts"]):
        raise FeatureInputError("Destination chart id already exists.")
    duplicated = copy.deepcopy(source)
    duplicated["id"] = values["newChartId"]
    state["charts"].append(duplicated)
    return _save(
        ctx,
        sheet,
        state,
        {
            "sourceChartId": source["id"],
            "newChartId": duplicated["id"],
            "seriesCount": len(duplicated["series"]),
        },
    )


@feature(
    "docCharts.chartData",
    "Chart Data",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("seriesName", "Series name", "Capacity"),
        text("xRange", "X values", "A1:A10"),
        text("yRange", "Y values", "B1:B10"),
    ],
)
def chart_data(ctx: FeatureContext, values: dict) -> dict:
    """Add or refresh a named chart series directly from two numeric worksheet ranges."""
    sheet, state, points = _rows(ctx, values, values["xRange"], values["yRange"])
    chart = _chart(state, values["chartId"])
    series = _range_series(values["seriesName"], [p[0] for p in points], [p[1] for p in points])
    existing = next(
        (i for i, s in enumerate(chart["series"]) if s["name"] == values["seriesName"]), None
    )
    if existing is None:
        chart["series"].append(series)
    else:
        chart["series"][existing] = series
    return _save(
        ctx,
        sheet,
        state,
        {
            "seriesName": values["seriesName"],
            "pointCount": len(points),
            "seriesCount": len(chart["series"]),
        },
    )


@feature(
    "docCharts.envelopePlot",
    "Envelope Plot",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("xRange", "Station values", "A1:A20"),
        text("caseRanges", "Response ranges, semicolon-separated", "B1:B20;C1:C20"),
        text("title", "Plot title", "Moment envelope"),
    ],
)
def envelope_plot(ctx: FeatureContext, values: dict) -> dict:
    """Build upper and lower response envelopes from multiple same-length load-case ranges."""
    sheet, state = _open(ctx, values)
    xs = [cell_value(a, state) for a in range_cells(values["xRange"])]
    cases = [
        [cell_value(a, state) for a in range_cells(item.strip())]
        for item in values["caseRanges"].split(";")
        if item.strip()
    ]
    if not cases or any(len(row) != len(xs) for row in cases):
        raise FeatureInputError("Every response range must match the station count.")
    upper = [max(row[i] for row in cases) for i in range(len(xs))]
    lower = [min(row[i] for row in cases) for i in range(len(xs))]
    chart = _new(
        state, values["chartId"], "envelope", values["title"], _range_series("Maximum", xs, upper)
    )
    chart["series"].append(_range_series("Minimum", xs, lower))
    return _save(
        ctx, sheet, state, {"stationCount": len(xs), "loadCases": len(cases), "seriesCount": 2}
    )


@feature(
    "docCharts.interactionDiagram",
    "Interaction Diagram",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("axialRange", "Axial force range", "A1:A20"),
        text("momentRange", "Moment range", "B1:B20"),
        text("title", "Diagram title", "P-M interaction"),
    ],
)
def interaction_diagram(ctx: FeatureContext, values: dict) -> dict:
    """Plot paired axial-force and moment-capacity points as a structural interaction diagram."""
    sheet, state, points = _rows(ctx, values, values["momentRange"], values["axialRange"])
    chart = _new(
        state,
        values["chartId"],
        "interaction",
        values["title"],
        _range_series("Capacity", [p[0] for p in points], [p[1] for p in points]),
    )
    chart["axes"] = {"x": {"title": "Moment [kN·m]"}, "y": {"title": "Axial force [kN]"}}
    return _save(ctx, sheet, state, {"capacityPoints": len(points)})


@feature(
    "docCharts.stressDiagram",
    "Stress Diagram",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("depthRange", "Section depth coordinates", "A1:A20"),
        text("stressRange", "Stress values", "B1:B20"),
        text("title", "Diagram title", "Section stress"),
    ],
)
def stress_diagram(ctx: FeatureContext, values: dict) -> dict:
    """Plot stress values against section depth for a calculated cross-section stress diagram."""
    sheet, state, points = _rows(ctx, values, values["depthRange"], values["stressRange"])
    points.sort(key=lambda p: p[0])
    chart = _new(
        state,
        values["chartId"],
        "stress",
        values["title"],
        _range_series("Stress", [p[0] for p in points], [p[1] for p in points]),
    )
    chart["axes"] = {"x": {"title": "Depth [mm]"}, "y": {"title": "Stress [MPa]"}}
    return _save(ctx, sheet, state, {"stressPoints": len(points)})


@feature(
    "docCharts.waterfallChart",
    "Waterfall Chart",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("categoryRange", "Change labels", "A1:A6"),
        text("changeRange", "Increment or decrement values", "B1:B6"),
        text("title", "Chart title", "Cost breakdown"),
    ],
)
def waterfall_chart(ctx: FeatureContext, values: dict) -> dict:
    """Calculate cumulative totals from a sequence of positive and negative component changes."""
    sheet, state, points = _rows(ctx, values, values["categoryRange"], values["changeRange"])
    cumulative = 0
    series = []
    for label, change in points:
        cumulative += change
        series.append({"x": label, "y": cumulative, "change": change})
    chart = _new(
        state,
        values["chartId"],
        "waterfall",
        values["title"],
        {"name": "Cumulative", "points": series, "axis": "primary"},
    )
    chart["waterfallBase"] = 0
    return _save(ctx, sheet, state, {"steps": len(series), "finalTotal": cumulative})


@feature(
    "docCharts.errorBars",
    "Error Bars",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("seriesName", "Series name", "Series 1"),
        number("error", "Symmetric error", 0.05, min=0),
        select(
            "direction",
            "Direction",
            [("both", "Both directions"), ("plus", "Positive only"), ("minus", "Negative only")],
            "both",
        ),
    ],
)
def error_bars(ctx: FeatureContext, values: dict) -> dict:
    """Attach symmetric or one-sided uncertainty bounds to every point in a named chart series."""
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    series = next((s for s in chart["series"] if s["name"] == values["seriesName"]), None)
    if series is None:
        raise FeatureInputError("Named chart series does not exist.")
    for point in series["points"]:
        point["errorBar"] = {
            "minus": 0 if values["direction"] == "plus" else values["error"],
            "plus": 0 if values["direction"] == "minus" else values["error"],
        }
    return _save(
        ctx,
        sheet,
        state,
        {
            "seriesName": series["name"],
            "pointsWithErrorBars": len(series["points"]),
            "error": values["error"],
        },
    )


@feature(
    "docCharts.trendline",
    "Trendline",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("seriesName", "Series name", "Series 1"),
    ],
)
def trendline(ctx: FeatureContext, values: dict) -> dict:
    """Fit a least-squares linear trendline to the selected chart series and store its coefficients."""
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    series = next((s for s in chart["series"] if s["name"] == values["seriesName"]), None)
    if series is None:
        raise FeatureInputError("Named chart series does not exist.")
    points = series["points"]
    n = len(points)
    sx = sum(float(p["x"]) for p in points)
    sy = sum(float(p["y"]) for p in points)
    sxx = sum(float(p["x"]) ** 2 for p in points)
    sxy = sum(float(p["x"]) * float(p["y"]) for p in points)
    den = n * sxx - sx * sx
    if n < 2 or den == 0:
        raise FeatureInputError("Trendline needs at least two points with distinct x values.")
    slope = (n * sxy - sx * sy) / den
    intercept = (sy - slope * sx) / n
    series["trendline"] = {"type": "linear", "slope": slope, "intercept": intercept}
    return _save(
        ctx,
        sheet,
        state,
        {
            "slope": slope,
            "intercept": intercept,
            "rSquared": 1
            - sum((p["y"] - (slope * p["x"] + intercept)) ** 2 for p in points)
            / (sum((p["y"] - sy / n) ** 2 for p in points) or 1),
        },
    )


@feature(
    "docCharts.referenceLines",
    "Reference Lines",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        select("axis", "Reference axis", [("x", "X"), ("y", "Y")], "y"),
        text("values", "Reference values, comma separated", "0,1"),
        text("labelPrefix", "Label prefix", "Limit"),
    ],
)
def reference_lines(ctx: FeatureContext, values: dict) -> dict:
    """Add horizontal or vertical engineering limit lines at one or more numeric chart coordinates."""
    try:
        levels = [float(v.strip()) for v in values["values"].split(",") if v.strip()]
    except ValueError as exc:
        raise FeatureInputError("Reference values must be numeric.") from exc
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    lines = chart.setdefault("referenceLines", [])
    lines.extend(
        {"axis": values["axis"], "value": level, "label": f"{values['labelPrefix']} {level:g}"}
        for level in levels
    )
    return _save(
        ctx,
        sheet,
        state,
        {"referenceLineCount": len(levels), "axis": values["axis"], "values": levels},
    )


@feature(
    "docCharts.secondaryAxis",
    "Secondary Axis",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("seriesName", "Series name", "Series 1"),
        text("axisTitle", "Secondary axis title", "Rotation"),
    ],
)
def secondary_axis(ctx: FeatureContext, values: dict) -> dict:
    """Assign one chart series to a secondary Y axis with an independent title."""
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    series = next((s for s in chart["series"] if s["name"] == values["seriesName"]), None)
    if series is None:
        raise FeatureInputError("Named chart series does not exist.")
    series["axis"] = "secondary"
    chart.setdefault("axes", {})["y2"] = {"title": values["axisTitle"]}
    return _save(
        ctx,
        sheet,
        state,
        {"seriesName": series["name"], "axis": "secondary", "axisTitle": values["axisTitle"]},
    )


@feature(
    "docCharts.colorPalette",
    "Colour Palette",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("colours", "Series colours, comma separated", "#4472C4,#ED7D31,#70AD47"),
    ],
)
def color_palette(ctx: FeatureContext, values: dict) -> dict:
    """Apply validated per-series hexadecimal colours to a chart."""
    colours = [item.strip() for item in values["colours"].split(",") if item.strip()]
    if any(not re.fullmatch(r"#[0-9A-Fa-f]{6}", item) for item in colours):
        raise FeatureInputError("Each series colour must use #RRGGBB format.")
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    for index, series in enumerate(chart["series"]):
        series["colour"] = colours[index % len(colours)]
    chart["style"]["palette"] = colours
    return _save(ctx, sheet, state, {"seriesCount": len(chart["series"]), "palette": colours})


@feature(
    "docCharts.chartTheme",
    "Chart Theme",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        select(
            "theme",
            "Theme",
            [
                ("engineering", "Engineering"),
                ("monochrome", "Monochrome"),
                ("presentation", "Presentation"),
            ],
            "engineering",
        ),
    ],
)
def chart_theme(ctx: FeatureContext, values: dict) -> dict:
    """Apply an explicit chart style theme with type-sized line and marker settings."""
    themes = {
        "engineering": {
            "font": "Aptos",
            "fontSizePt": 10,
            "lineWidthPx": 2,
            "markerRadiusPx": 3,
            "background": "#FFFFFF",
        },
        "monochrome": {
            "font": "Arial",
            "fontSizePt": 9,
            "lineWidthPx": 1.5,
            "markerRadiusPx": 2,
            "background": "#FFFFFF",
        },
        "presentation": {
            "font": "Aptos Display",
            "fontSizePt": 13,
            "lineWidthPx": 3,
            "markerRadiusPx": 5,
            "background": "#F7F9FC",
        },
    }
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    chart["style"].update(themes[values["theme"]])
    chart["style"]["theme"] = values["theme"]
    return _save(ctx, sheet, state, {"chartId": chart["id"], "theme": values["theme"]})


@feature(
    "docCharts.gridlinesSetup",
    "Gridlines Setup",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        checkbox("horizontal", "Horizontal gridlines", True),
        checkbox("vertical", "Vertical gridlines", False),
        text("colour", "Gridline colour", "#DDDDDD"),
    ],
)
def gridlines_setup(ctx: FeatureContext, values: dict) -> dict:
    """Set horizontal and vertical chart gridline visibility and line colour."""
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", values["colour"]):
        raise FeatureInputError("Gridline colour must use #RRGGBB format.")
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    chart["gridlines"] = {
        "x": values["vertical"],
        "y": values["horizontal"],
        "colour": values["colour"],
    }
    return _save(
        ctx, sheet, state, {"horizontal": values["horizontal"], "vertical": values["vertical"]}
    )


@feature(
    "docCharts.selectSeries",
    "Select Series",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("seriesName", "Series name", "Series 1"),
        checkbox("visible", "Show selected series", True),
    ],
)
def select_series(ctx: FeatureContext, values: dict) -> dict:
    """Show or hide one named chart series without removing its data."""
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    series = next((s for s in chart["series"] if s["name"] == values["seriesName"]), None)
    if series is None:
        raise FeatureInputError("Named chart series does not exist.")
    series["visible"] = values["visible"]
    return _save(ctx, sheet, state, {"seriesName": series["name"], "visible": values["visible"]})


@feature(
    "docCharts.filterSeries",
    "Filter Series",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        text("seriesName", "Series name", "Series 1"),
        number("minimumX", "Minimum X", 0),
        number("maximumX", "Maximum X", 100),
    ],
)
def filter_series(ctx: FeatureContext, values: dict) -> dict:
    """Filter a chart series to points within a numeric x-domain and retain the original point count."""
    if values["minimumX"] > values["maximumX"]:
        raise FeatureInputError("Minimum X cannot exceed maximum X.")
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    series = next((s for s in chart["series"] if s["name"] == values["seriesName"]), None)
    if series is None:
        raise FeatureInputError("Named chart series does not exist.")
    original = series.setdefault("sourcePoints", series["points"])
    series["points"] = [
        p for p in original if values["minimumX"] <= float(p["x"]) <= values["maximumX"]
    ]
    series["filter"] = {"minimumX": values["minimumX"], "maximumX": values["maximumX"]}
    return _save(
        ctx,
        sheet,
        state,
        {
            "seriesName": series["name"],
            "visiblePointCount": len(series["points"]),
            "sourcePointCount": len(original),
        },
    )


@feature(
    "docCharts.smoothCurves",
    "Smooth Curves",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("chartId", "Chart id", "chart-1"),
        checkbox("smooth", "Smooth line series", True),
        number("tension", "Curve tension", 0.5, min=0, max=1),
    ],
)
def smooth_curves(ctx: FeatureContext, values: dict) -> dict:
    """Set spline smoothing metadata for line series and retain the tension used by SVG export."""
    sheet, state = _open(ctx, values)
    chart = _chart(state, values["chartId"])
    if chart["type"] not in ("line", "scatter", "envelope"):
        raise FeatureInputError("Curve smoothing applies to line, scatter and envelope charts.")
    chart["smoothing"] = {"enabled": values["smooth"], "tension": values["tension"]}
    return _save(
        ctx,
        sheet,
        state,
        {"chartId": chart["id"], "smooth": values["smooth"], "tension": values["tension"]},
    )
