"""Post-Tensioning - Design tab (#285): the tendon groups of the building model (6 BIM, Additions,
Slab tendons) designed strip by strip (saengine.design.prestress through
saengine.design.check.tendon_designs, as the design run does): their layout and balanced
load, the losses, the stresses at transfer and service, and the strength.

Every limit, method and clause is the project's code pack's; a pack without prestressed
concrete says so. No analysis is needed: each strip is a continuous beam on the profile's high
points. Each run also writes a strip view (``08 FEM/pt/<slab>-<tendon>.svg``): the profile, the
force after each loss and the fibre stresses against the pack's limits.
"""

from __future__ import annotations

import math
from html import escape
from pathlib import Path
from typing import Any

import numpy as np

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.fem_common import load_bim, load_materials, load_objects, load_settings

_TENDON = text(
    "tendon",
    "Tendon group (empty: all)",
    "",
    help="Id of one tendon group, or a slab id for all of its groups; empty: every group.",
)


def _designs(ctx: FeatureContext, which: str) -> tuple[list[dict[str, Any]], list[str], Any]:
    """The designs of the tendon groups (all, or those of ``which``: a group or slab id) and
    their notes, under the project's code pack; and the pack's prestress limits."""
    from saengine.design import check as design_check
    from saengine.design import prestress
    from saengine.report.clauses import in_force

    bim = load_bim(ctx)
    if bim is None:
        raise FeatureInputError("Open a project with a building model (6 BIM) first.")
    if not bim.additions.slabTendons:
        raise FeatureInputError(
            "The building model has no tendon groups: add them in 6 BIM, Additions, Slab tendons."
        )
    _, types = load_objects(ctx)
    _, mats = load_materials(ctx)
    settings = load_settings(ctx)
    with in_force(ctx.root, settings) as problems:
        try:
            limits = prestress.limits()
        except ValueError:
            from saengine.codes import context as code_context

            raise FeatureInputError(
                f"Post-tensioned slab design is not provided by the code pack "
                f"{code_context.current().name}."
            ) from None
        rows, notes = design_check.tendon_designs(bim, types, mats, settings)
    notes = list(problems) + notes
    if which:
        rows = [r for r in rows if which in (r["tendon"].id, r["slab"])]
        if not rows:
            raise FeatureInputError(f"No designed tendon group or slab '{which}'.")
    if not rows:
        raise FeatureInputError("No tendon group could be designed: " + "; ".join(notes[:4]))
    return rows, notes, limits


def _row_notes(rows: list[dict[str, Any]], notes: list[str]) -> list[str]:
    out = list(notes)
    for r in rows:
        out += [f"{r['slab']}: {n}" for n in r["design"].notes]
    return out


def _check(design: Any, suffix: str) -> dict[str, Any] | None:
    return next((c for c in design.checks if c["name"].endswith(suffix)), None)


def _station_rows(row: dict[str, Any], keys: list[tuple[str, Any]], points: int = 11):
    """Rows at ``points`` evenly spaced stations of the strip (interpolated)."""
    diagrams = row["design"].diagrams
    stations = diagrams["stations"]
    out = []
    for x in np.linspace(float(stations[0]), float(stations[-1]), points):
        entry: dict[str, Any] = {"tendon": row["tendon"].id, "x": round(float(x) / 1e3, 2)}
        for key, values in keys:
            entry[key] = round(float(np.interp(x, stations, values)), 2)
        out.append(entry)
    return out


# ─────────────────────────────────────── strip view (SVG) ───────────────────────────────────────


def _polyline(xs: np.ndarray, ys: np.ndarray, box: tuple[float, float, float, float],
              x_range: tuple[float, float], y_range: tuple[float, float], colour: str,
              dash: str = "") -> str:  # fmt: skip
    left, top, width, height = box
    x0, x1 = x_range
    y0, y1 = y_range
    span_y = (y1 - y0) or 1.0
    pts = " ".join(
        f"{left + (x - x0) / (x1 - x0) * width:.1f},{top + (y1 - y) / span_y * height:.1f}"
        for x, y in zip(xs, ys, strict=True)
    )
    style = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<polyline fill="none" stroke="{colour}" stroke-width="1.6"{style} points="{pts}"/>'


def axis_label(value: float) -> str:
    """An axis value as an engineer reads it: whole numbers from 100 up ("1470", not
    "1.47e+03"), else up to three significant figures ("3.5", "0.25")."""
    if abs(value) >= 100:
        return f"{value:.0f}"
    return f"{value:.3g}"


def strip_view(row: dict[str, Any], out_dir: Path) -> Path:
    """The strip view of a tendon group: its profile in the slab, the force along it after each
    loss and the fibre stresses at transfer and service with the pack's limits."""
    tendon, design = row["tendon"], row["design"]
    d = design.diagrams
    xs = d["stations"]
    x_range = (float(xs[0]), float(xs[-1]))
    w, left, plot_w = 900, 70, 800
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="760" '
            'font-family="Segoe UI, Arial, sans-serif" font-size="12">'
        ),
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        (
            f'<text x="{left}" y="24" font-size="15" font-weight="600">'
            f"{escape(row['slab'])} / {escape(tendon.id)}: post-tensioned strip "
            f"({escape(tendon.layout)}, {tendon.count} × {tendon.strands} strands, "
            f"{'bonded' if tendon.bonded else 'unbonded'})</text>"
        ),
    ]

    def frame(top: float, height: float, title: str, y_range: tuple[float, float],
              unit: str) -> tuple[float, float, float, float]:  # fmt: skip
        parts.append(f'<text x="{left}" y="{top - 8}" font-weight="600">{escape(title)}</text>')
        parts.append(
            f'<rect x="{left}" y="{top}" width="{plot_w}" height="{height}" fill="none" '
            'stroke="#999"/>'
        )
        for value in (y_range[0], (y_range[0] + y_range[1]) / 2, y_range[1]):
            y = top + (y_range[1] - value) / ((y_range[1] - y_range[0]) or 1) * height
            parts.append(
                f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{axis_label(value)}</text>'
            )
        parts.append(
            f'<text x="{left - 6}" y="{top + height + 14}" text-anchor="end" fill="#666">{unit}</text>'
        )
        return (left, top, plot_w, height)

    # 1 Profile within the slab (heights above the soffit).
    h = row["h"]
    box = frame(60, 110, "Tendon profile: CGS above the soffit", (0.0, h), "mm")
    parts.append(_polyline(xs, d["heights"], box, x_range, (0.0, h), "#c0392b"))
    for s in design.balance:
        x = left + (s.low - x_range[0]) / (x_range[1] - x_range[0]) * plot_w
        parts.append(
            f'<text x="{x:.1f}" y="{60 + 110 + 14}" text-anchor="middle" fill="#555">'
            f"a = {s.drape:.0f} mm, w = {s.load:.1f} kN/m</text>"
        )
    # 2 Forces.
    f = design.forces
    stages = [
        (f.friction, "#7f8c8d", "after friction"),
        (f.after_set, "#2980b9", "after anchor set"),
        (f.initial, "#27ae60", "after elastic shortening (transfer)"),
        (f.effective, "#8e44ad", "effective (long-term)"),
    ]
    high = float(f.jacking) / 1e3
    low = min(float(np.min(s[0])) for s in stages) / 1e3
    y_range = (math.floor(low * 0.95), math.ceil(high))
    box = frame(230, 150, "Tendon force [kN]", y_range, "kN")
    for k, (values, colour, label) in enumerate(stages):
        parts.append(_polyline(xs, values / 1e3, box, x_range, y_range, colour))
        parts.append(
            f'<text x="{left + 10 + 200 * k}" y="{230 + 150 + 16}" fill="{colour}">'
            f"{escape(label)}</text>"
        )
    # 3 Stresses.
    curves = [
        (d["transferTop"], "#e67e22", "", "transfer top"),
        (d["transferBottom"], "#e67e22", "5,3", "transfer bottom"),
        (d["serviceTop"], "#2c3e50", "", "service top"),
        (d["serviceBottom"], "#2c3e50", "5,3", "service bottom"),
    ]
    limits = []
    for suffix, colour in (
        ("service compression", "#c0392b"),
        ("transfer compression", "#d35400"),
    ):
        found = _check(design, suffix)
        if found:
            limits.append((float(found["capacity"]), colour, suffix + " limit"))
    tension = _check(design, "service tension")
    if tension:
        limits.append((-float(tension["capacity"]), "#c0392b", "service tension limit"))
    values = np.concatenate([c[0] for c in curves] + [np.array([v for v, _, _ in limits] or [0])])
    y_range = (math.floor(float(values.min())) - 1, math.ceil(float(values.max())) + 1)
    box = frame(440, 230, "Fibre stresses [MPa], compression positive", y_range, "MPa")
    for values_, colour, dash, _ in curves:
        parts.append(_polyline(xs, values_, box, x_range, y_range, colour, dash))
    for value, colour, _ in limits:
        parts.append(_polyline(np.array(x_range), np.array([value, value]), box, x_range, y_range,
                               colour, "2,4"))  # fmt: skip
    legend = [(c[1], c[2], c[3]) for c in curves] + [(c, "2,4", t) for _, c, t in limits]
    for k, (colour, dash, label) in enumerate(legend):
        x = left + 10 + 200 * (k % 4)
        y = 440 + 230 + 18 + 16 * (k // 4)
        style = f' stroke-dasharray="{dash}"' if dash else ""
        parts.append(
            f'<line x1="{x}" y1="{y - 4}" x2="{x + 22}" y2="{y - 4}" stroke="{colour}"'
            f' stroke-width="2"{style}/>'
            f'<text x="{x + 28}" y="{y}">{escape(label)}</text>'
        )
    parts.append(
        f'<text x="{left}" y="745" fill="#666">Distance along the tendon: 0 to '
        f"{x_range[1] / 1e3:.2f} m. Limits and methods: the project's code pack.</text>"
    )
    parts.append("</svg>")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{row['slab']}-{tendon.id}.svg".replace("/", "_")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _views(ctx: FeatureContext, rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    out_dir = ctx.path("08 FEM/pt")
    if out_dir is None:
        return []
    files = []
    for r in rows:
        try:
            path = strip_view(r, out_dir)
        except OSError:
            continue
        files.append({"label": f"Strip view {r['slab']} / {r['tendon'].id}", "path": str(path)})
    return files


# ─────────────────────────────────────── the features ───────────────────────────────────────


@feature(
    "design.tendonLayout",
    "Tendon Layout",
    part="fem",
    fields=[
        _TENDON,
        number(
            "balancedShare",
            "Target balanced share of the self-weight",
            80,
            unit="%",
            min=0,
            max=150,
            help="The tendons needed to balance this share of the strip's self-weight per span.",
        ),
    ],
    help="The tendon groups of the building model: layout, strands, profile, drape and the "
    "balanced load w = 8 P a / L² of each span at the effective force.",
)
def tendon_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Each group's layout, and per span its drape, balanced load and the tendons a target
    share of the self-weight needs."""
    rows, notes, _ = _designs(ctx, str(values.get("tendon") or "").strip())
    target = float(values.get("balancedShare", 80) or 0) / 100
    groups, spans = [], []
    for r in rows:
        t, design = r["tendon"], r["design"]
        aps = design.forces.area
        p_e = float(np.mean(design.forces.effective))
        groups.append(
            {
                "slab": r["slab"],
                "tendon": t.id,
                "layout": t.layout,
                "direction": r["direction"],
                "width": round(float(t.width)),
                "tendons": f"{t.count} × {t.strands}",
                "aps": round(aps),
                "jacking": round(t.jacking * t.fpu),
                "liveEnd": t.stressedAt,
                "profile": "; ".join(f"{p.at / 1e3:g} m: {p.height:g}" for p in t.profile),
                "pe": round(p_e / 1e3, 1),
            }
        )
        # The strip's self-weight [N/mm = kN/m] (its load per plan area times the width).
        self_weight = design.loads.dead * float(t.width) if design.loads else 0.0
        for s in design.balance:
            per_tendon = s.load / t.count if t.count else 0.0
            needed = (
                math.ceil(target * self_weight / per_tendon)
                if per_tendon > 0 and self_weight
                else None
            )
            spans.append(
                {
                    "tendon": t.id,
                    "span": f"{s.start / 1e3:.2f}-{s.end / 1e3:.2f}",
                    "length": round(s.length / 1e3, 2),
                    "drape": round(s.drape, 1),
                    "w": round(s.load, 2),
                    "mean": round(s.mean, 2),
                    "share": round(100 * s.load / self_weight, 0) if self_weight else None,
                    "needed": needed,
                }
            )
    return result(
        summary={"groups": len(groups), "spans": len(spans)},
        tables=[
            table(
                "Tendon groups",
                [
                    ("slab", "Slab"),
                    ("tendon", "Group"),
                    ("layout", "Layout"),
                    ("direction", "Along"),
                    ("width", "Strip width", "mm"),
                    ("tendons", "Tendons × strands"),
                    ("aps", "Aps", "mm²"),
                    ("jacking", "fpj", "MPa"),
                    ("liveEnd", "Live end"),
                    ("profile", "Profile (distance: CGS height mm)"),
                    ("pe", "Effective P", "kN"),
                ],
                groups,
            ),
            table(
                "Balanced load per span (w = 8 P a / L², P effective)",
                [
                    ("tendon", "Group"),
                    ("span", "Span", "m"),
                    ("length", "L", "m"),
                    ("drape", "Drape a", "mm"),
                    ("w", "w balanced", "kN/m"),
                    ("mean", "Mean P y''", "kN/m"),
                    ("share", "Of self-weight", "%"),
                    ("needed", f"Tendons for {target * 100:g} %"),
                ],
                spans,
            ),
        ],
        notes=[
            (
                "a: the chord between the support heights at the low point, less the low point; "
                "the supports are the profile's high points."
            ),
            *_row_notes(rows, notes)[:12],
        ],
    ) | {"outputFiles": _views(ctx, rows)}


@feature(
    "design.ptLosses",
    "PT Losses",
    part="fem",
    fields=[_TENDON],
    help="Prestress losses of each tendon group: friction and wobble, anchor set, elastic "
    "shortening, creep, shrinkage and relaxation (or the long-term loss entered).",
)
def pt_losses(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """The losses of each group and its force along the strip."""
    rows, notes, _ = _designs(ctx, str(values.get("tendon") or "").strip())
    summary_rows, station_rows = [], []
    for r in rows:
        t, design = r["tendon"], r["design"]
        f = design.forces
        aps = f.area
        fpj = f.jacking / aps
        friction_far = float(np.min(f.friction)) / aps
        after_set = float(np.mean(f.after_set)) / aps
        initial = float(np.mean(f.initial)) / aps
        effective = float(np.mean(f.effective)) / aps
        lt = design.losses
        summary_rows.append(
            {
                "tendon": t.id,
                "fpj": round(fpj),
                "friction": round(fpj - friction_far, 1),
                "setLength": round(f.set_length / 1e3, 2),
                "anchorSet": round(
                    fpj - float(f.after_set[0 if t.stressedAt != "end" else -1]) / aps, 1
                ),
                "elastic": round(f.elastic, 1),
                "creep": round(lt.creep, 1) if lt else None,
                "shrinkage": round(lt.shrinkage, 1) if lt else None,
                "relaxation": round(lt.relaxation, 1) if lt else None,
                "longTerm": round(f.long_term, 1),
                "fpi": round(initial),
                "fpe": round(effective),
                "total": round(100 * (1 - effective / fpj), 1),
                "meanAfterSet": round(after_set),
            }
        )
        station_rows += _station_rows(
            r,
            [
                ("friction", f.friction / 1e3),
                ("afterSet", f.after_set / 1e3),
                ("initial", f.initial / 1e3),
                ("effective", f.effective / 1e3),
            ],
        )
    return result(
        summary={"groups": len(rows)},
        tables=[
            table(
                "Losses per tendon group (stresses in the strand)",
                [
                    ("tendon", "Group"),
                    ("fpj", "fpj", "MPa"),
                    ("friction", "Friction + wobble at the far end", "MPa"),
                    ("anchorSet", "Anchor set at the live end", "MPa"),
                    ("setLength", "Set length", "m"),
                    ("elastic", "Elastic shortening", "MPa"),
                    ("creep", "Creep", "MPa"),
                    ("shrinkage", "Shrinkage", "MPa"),
                    ("relaxation", "Relaxation", "MPa"),
                    ("longTerm", "Long-term total", "MPa"),
                    ("fpi", "Mean after transfer", "MPa"),
                    ("fpe", "Mean effective fse", "MPa"),
                    ("total", "Total loss", "%"),
                ],
                summary_rows,
            ),
            table(
                "Force along the tendon",
                [
                    ("tendon", "Group"),
                    ("x", "x", "m"),
                    ("friction", "After friction", "kN"),
                    ("afterSet", "After anchor set", "kN"),
                    ("initial", "After transfer", "kN"),
                    ("effective", "Effective", "kN"),
                ],
                station_rows,
            ),
        ],
        notes=[
            (
                "Friction P = Pj e^-(K x + μ α); the anchor set mirrors the friction near the live end "
                "over the set length; elastic shortening 0.5 (Ep / Eci) fcp; creep, shrinkage and "
                "relaxation by the code pack (empty when the long-term loss is entered)."
            ),
            *_row_notes(rows, notes)[:12],
        ],
    ) | {"outputFiles": _views(ctx, rows)}


@feature(
    "design.ptStresses",
    "PT Stresses",
    part="fem",
    fields=[_TENDON],
    help="Concrete stresses at transfer and service along each tendon group against the code "
    "pack's limits, the member class and the precompression.",
)
def pt_stresses(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """The stress checks of each group and its fibre stresses along the strip."""
    rows, notes, _ = _designs(ctx, str(values.get("tendon") or "").strip())
    words = ("transfer", "service", "sustained", "precompression", "Class C", "tendon stress",
             "anchors", "spacing")  # fmt: skip
    checks, stations = [], []
    for r in rows:
        design = r["design"]
        for c in design.checks:
            if any(w in c["name"] for w in words) and "deflection" not in c["name"]:
                checks.append(_check_row(r, c))
        d = design.diagrams
        stations += _station_rows(
            r,
            [
                ("transferTop", d["transferTop"]),
                ("transferBottom", d["transferBottom"]),
                ("serviceTop", d["serviceTop"]),
                ("serviceBottom", d["serviceBottom"]),
                ("sustainedTop", d["sustainedTop"]),
                ("sustainedBottom", d["sustainedBottom"]),
            ],
        )
    classes = {r["tendon"].id: r["design"].member_class for r in rows}
    return result(
        summary={
            "checks": len(checks),
            "failing": sum(1 for c in checks if not c["ok"]),
            "classes": ", ".join(f"{k}: {v}" for k, v in classes.items()),
        },
        tables=[
            table("Stress checks", _CHECK_COLUMNS, checks),
            table(
                "Fibre stresses along the strip (compression positive)",
                [
                    ("tendon", "Group"),
                    ("x", "x", "m"),
                    ("transferTop", "Transfer top", "MPa"),
                    ("transferBottom", "Transfer bottom", "MPa"),
                    ("serviceTop", "Service top", "MPa"),
                    ("serviceBottom", "Service bottom", "MPa"),
                    ("sustainedTop", "Sustained top", "MPa"),
                    ("sustainedBottom", "Sustained bottom", "MPa"),
                ],
                stations,
            ),
        ],
        notes=[
            (
                "f = P / A ± M / S, M the gravity moments plus the balanced moment of the tendons "
                "(transfer: self-weight with P after the immediate losses; service: D + SD + L with "
                "the effective P)."
            ),
            *_row_notes(rows, notes)[:12],
        ],
    ) | {"outputFiles": _views(ctx, rows)}


_CHECK_COLUMNS = [
    ("slab", "Slab"),
    ("check", "Check"),
    ("demand", "Value"),
    ("capacity", "Limit"),
    ("unit", "Unit"),
    ("utilisation", "Ratio"),
    ("ok", "OK"),
    ("note", "How"),
]


def _check_row(row: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    return {
        "slab": row["slab"],
        "check": c["name"],
        "demand": c["demand"],
        "capacity": c["capacity"],
        "unit": c["unit"],
        "utilisation": c["utilisation"],
        "ok": c["ok"],
        "note": c["note"],
    }


@feature(
    "design.ptUltimate",
    "PT Ultimate",
    part="fem",
    fields=[_TENDON],
    help="Flexural strength of each tendon group: the code pack's gravity combinations plus "
    "1.0 times the hyperstatic moment against φMn with the bonded or unbonded fps.",
)
def pt_ultimate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """The governing strength section of each group, and its other strength checks."""
    rows, notes, _ = _designs(ctx, str(values.get("tendon") or "").strip())
    sections, checks = [], []
    words = ("strength", "bonded", "integrity", "deflection")
    for r in rows:
        u = r["design"].ultimate
        if u:
            sections.append(
                {
                    "tendon": r["tendon"].id,
                    "at": round(u["at"] / 1e3, 2),
                    "face": "sagging" if u["sagging"] else "hogging",
                    "combination": u["combination"],
                    "m2": round(u["m2"], 2),
                    "mu": round(u["mu"], 2),
                    "fse": round(u["fse"]),
                    "fps": round(u["fps"]),
                    "dp": round(u["dp"]),
                    "a": round(float(u["a"]), 1),
                    "phi": round(u["phi"], 3),
                    "phiMn": round(float(u["phiMn"]), 2),
                    "ratio": round(float(u["ratio"]), 3),
                    "ok": bool(u["ratio"] <= 1.0),
                }
            )
        for c in r["design"].checks:
            if any(w in c["name"] for w in words) and not c["name"].endswith("flexural strength"):
                checks.append(_check_row(r, c))
    return result(
        summary={
            "groups": len(sections),
            "failing": sum(1 for s in sections if not s["ok"]),
        },
        tables=[
            table(
                "Flexural strength (governing section of each group)",
                [
                    ("tendon", "Group"),
                    ("at", "x", "m"),
                    ("face", "Moment"),
                    ("combination", "Combination"),
                    ("m2", "M2 hyperstatic", "kN·m"),
                    ("mu", "Mu", "kN·m"),
                    ("fse", "fse", "MPa"),
                    ("fps", "fps", "MPa"),
                    ("dp", "dp", "mm"),
                    ("a", "a", "mm"),
                    ("phi", "φ"),
                    ("phiMn", "φMn", "kN·m"),
                    ("ratio", "Mu / φMn"),
                    ("ok", "OK"),
                ],
                sections,
            ),
            table("Reinforcement, deflection and other checks", _CHECK_COLUMNS, checks),
        ],
        notes=[
            (
                "Unbonded fps by the pack's span/depth rule; bonded fps = fpu (1 - γp / β1 ρp fpu / "
                "f'c); a = (Aps fps + As fy) / (0.85 f'c b); φ from the net tensile strain."
            ),
            *_row_notes(rows, notes)[:12],
        ],
    ) | {"outputFiles": _views(ctx, rows)}
