"""Design - Slab Checks: cracked long-term deflection and crack widths of the slabs analysed as
shells (#302, :mod:`saengine.design.slab_service`).

The design run (Run Design or Run All) computes them with the project's settings (the
sustained share of the live load, the partitions) and keeps what it collected in the design
report; these buttons show them per design strip, worked again with the inputs given here, so
ψ, the months, φ and the exposure can be tried without a new design run. The slabs' contours
are in the results bar (Slab Long-Term Deflection, Slab Crack Width).
"""

from __future__ import annotations

import json
from typing import Any

from saengine.design import slab_service
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
from saengine.features.fem_common import require_results
from saengine.report.clauses import in_force

_PARTITIONS = [
    ("sensitive", "Likely to be damaged (masonry partitions)"),
    ("insensitive", "Not likely to be damaged"),
]


def _slabs(ctx: FeatureContext) -> list[tuple[str, slab_service.SlabServiceData]]:
    """The slabs of the last design run with their collected service data."""
    out_dir, _ = require_results(ctx)
    path = out_dir / "design-report.json"
    if not path.is_file():
        raise FeatureInputError("Run the design first (Design > Run Design).")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"The design report could not be read: {error}") from error
    # The design run keeps the report as {stamp, computed, result} (pipeline.design_mode).
    report = report.get("result", report) if isinstance(report, dict) else {}
    found = []
    for element in report.get("elements", []):
        raw = (element.get("service") or {}).get("data")
        if element.get("kind") == "slab" and raw:
            found.append((str(element["id"]), slab_service.SlabServiceData.from_dict(raw)))
    if not found:
        raise FeatureInputError(
            "No slab analysed as shells has service results: set the analysis's slabs to "
            "shells, enter the slabs' bars and run the design again."
        )
    return found


def _inputs(values: dict[str, Any]) -> slab_service.Inputs:
    creep = float(values.get("creep") or 0.0)
    return slab_service.Inputs(
        sustained=float(values.get("sustained", 0.25)),
        months=float(values.get("months", 60.0)),
        sensitive=values.get("partitions", "sensitive") == "sensitive",
        creep=creep if creep > 0 else None,
        exposure=(str(values.get("exposure") or "").strip() or None),
    )


@feature(
    "design.crackedDeflection",
    "Cracked Deflection",
    part="fem",
    fields=[
        number(
            "sustained",
            "Sustained share of the live load ψ",
            0.25,
            min=0.0,
            max=1.0,
            help="The quasi-permanent load is D + ψ L (Project Settings > Analysis keeps the "
            "design run's value).",
        ),
        number("months", "Load sustained for", 60.0, unit="months", min=3.0, max=600.0),
        select("partitions", "Partitions", _PARTITIONS, "sensitive"),
        number(
            "creep",
            "Creep coefficient φ (0: the code's)",
            0.0,
            min=0.0,
            max=6.0,
            help="Codes that work the long-term part from φ (ζ interpolation, Annex C type).",
        ),
    ],
    help="Long-term cracked deflection of the slabs analysed as shells, per design strip: the "
    "analysis's deflection scaled to the cracked stiffness of the bars entered, with creep and "
    "shrinkage by the code pack's method, against the code's span limits.",
)
def cracked_deflection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Cracked long-term deflection of the FE slabs per design strip (see the module notes)."""
    inputs = _inputs(values)
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    method = None
    with in_force(ctx.root):
        for slab_id, data in _slabs(ctx):
            evaluated = slab_service.evaluate(data, inputs)
            method = evaluated.deflection_method
            notes += evaluated.notes
            for span in evaluated.spans:
                worst = max(span["checks"], key=lambda c: c["value"] / max(c["limit"], 1e-9))
                rows.append(
                    {
                        "slab": slab_id,
                        "strip": span["strip"],
                        "spanM": span["span"] / 1e3,
                        "immediateMm": round(span["immediate"], 1),
                        "longTermMm": round(span["longTerm"], 1),
                        "totalMm": round(span["total"], 1),
                        "afterMm": round(span["after"], 1),
                        "check": worst["name"].split(" (FE")[0],
                        "limitMm": round(worst["limit"], 1),
                        "ok": all(c["ok"] for c in span["checks"]),
                    }
                )
    if method is None:
        return result(
            summary={"method": slab_service.NOT_PROVIDED},
            notes=[f"Cracked deflection of slabs is {slab_service.NOT_PROVIDED}.", *notes],
        )
    rows.sort(key=lambda r: -r["totalMm"])
    return result(
        summary={
            "method": slab_service.METHOD_NAMES[method],
            "strips": len(rows),
            "failing": sum(1 for r in rows if not r["ok"]),
            "largestDeflection": f"{max((r['totalMm'] for r in rows), default=0.0):.1f} mm",
        },
        tables=[
            table(
                "Cracked long-term deflection per design strip",
                [
                    ("slab", "Slab"),
                    ("strip", "Strip"),
                    ("spanM", "Span", "m"),
                    ("immediateMm", "Immediate", "mm"),
                    ("longTermMm", "Long-term part", "mm"),
                    ("totalMm", "Total", "mm"),
                    ("afterMm", "After partitions", "mm"),
                    ("check", "Governing limit"),
                    ("limitMm", "Limit", "mm"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[
            f"Method of the code in force: {slab_service.METHOD_NAMES[method]}.",
            "The contour is in the results bar: Show > Slab Long-Term Deflection (with the "
            + "design run's inputs).",
            *notes,
        ],
    )


@feature(
    "design.crackWidths",
    "Crack Widths",
    part="fem",
    fields=[
        number(
            "sustained",
            "Sustained share of the live load ψ",
            0.25,
            min=0.0,
            max=1.0,
            help="Codes that take the crack width under the quasi-permanent load D + ψ L.",
        ),
        text(
            "exposure",
            "Exposure class (blank: the project's)",
            "",
            help="An exposure of the code pack's crack width table, e.g. XC3, moderate.",
        ),
    ],
    help="Crack widths of the slabs analysed as shells at mid-span and at the supports of each "
    "design strip, from the steel stress of the bars entered under service loads, by the code "
    "pack's method, against the exposure's limit (or the bar spacing rule where the code gives "
    "no crack width).",
)
def crack_widths(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Crack widths of the FE slabs per design strip station (see the module notes)."""
    inputs = _inputs(values)
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    method = None
    with in_force(ctx.root):
        for slab_id, data in _slabs(ctx):
            evaluated = slab_service.evaluate(data, inputs, deflection=False)
            method = evaluated.crack_method
            notes += evaluated.notes
            digits = 0 if method == "barSpacing" else 2  # spacing [mm] or width [mm]
            rows += [
                {
                    "slab": slab_id,
                    "strip": c["strip"],
                    "at": f"{c['at']} ({c['face']} bars)",
                    "momentKnm": round(c["moment"], 1),
                    "value": round(c["value"], digits),
                    "limit": round(c["limit"], digits),
                    "exposure": c["exposure"],
                    "ok": c["ok"],
                }
                for c in evaluated.cracks
            ]
    if method is None:
        return result(
            summary={"method": slab_service.NOT_PROVIDED},
            notes=[f"Crack widths of slabs are {slab_service.NOT_PROVIDED}.", *notes],
        )
    spacing = method == "barSpacing"
    rows.sort(key=lambda r: -(r["value"] / max(r["limit"], 1e-9)))
    return result(
        summary={
            "method": slab_service.METHOD_NAMES[method],
            "stations": len(rows),
            "failing": sum(1 for r in rows if not r["ok"]),
        },
        tables=[
            table(
                "Bar spacing at service per design strip"
                if spacing
                else "Crack widths per design strip",
                [
                    ("slab", "Slab"),
                    ("strip", "Strip"),
                    ("at", "Where"),
                    ("momentKnm", "Service moment", "kN·m/m"),
                    ("value", "Bar spacing" if spacing else "Crack width wk", "mm"),
                    ("limit", "Allowed spacing" if spacing else "Limit wmax", "mm"),
                    ("exposure", "Exposure"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[
            f"Method of the code in force: {slab_service.METHOD_NAMES[method]}"
            + (" (the code gives no crack width calculation)." if spacing else "."),
            "The contour is in the results bar: Show > Slab Crack Width.",
            *notes,
        ],
    )
