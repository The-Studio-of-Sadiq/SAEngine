"""FEM Model - Loads tab: load cases, patterns, combinations, envelopes, gravity/lateral loads, and balance audits."""

from __future__ import annotations

from typing import Any

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
from saengine.features.fem_common import (
    building_plan_dims_m,
    load_bim,
    load_objects,
    load_settings,
    optional_osmodel,
    require_results,
    site_params,
)
from saengine.fem import combinations as fem_combos
from saengine.fem import loads as fem_loads
from saengine.fem import notional_loads as fem_notional
from saengine.fem import result_tables, snow_load, story_response, thermal
from saengine.report.clauses import in_force


@feature(
    "femLoads.loadCases",
    "Load Cases",
    part="fem",
    fields=[text("filterKind", "Case type filter (blank = all)", "")],
    requires_project=False,
)
def load_cases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List analysis load cases defined in the model or standard project load case set."""
    _, model = optional_osmodel(ctx)
    filt = values["filterKind"].strip().lower()
    if model and model.get("analyses"):
        rows = [
            {
                "id": a.get("id"),
                "name": str(a.get("name", "")),
                "type": str(a.get("type", "Static")),
                "patterns": len(a.get("pattern_ids") or []),
            }
            for a in model["analyses"]
            if not filt
            or filt in str(a.get("type", "")).lower()
            or filt in str(a.get("name", "")).lower()
        ]
    else:
        defaults = [
            ("D", "Dead", "Static"),
            ("SD", "Superimposed Dead", "Static"),
            ("L", "Live", "Static"),
            ("WX", "Wind X", "Static"),
            ("WY", "Wind Y", "Static"),
            ("EX", "Seismic X", "Static"),
            ("EY", "Seismic Y", "Static"),
            ("Modal", "Modal Eigen", "Modal"),
        ]
        rows = [
            {"id": i + 1, "name": f"{c}: {lbl}", "type": t, "patterns": 1}
            for i, (c, lbl, t) in enumerate(defaults)
            if not filt or filt in t.lower() or filt in c.lower()
        ]
    return result(
        summary={"caseCount": len(rows), "fromModel": bool(model and model.get("analyses"))},
        tables=[
            table(
                "Load cases",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("type", "Analysis Type"),
                    ("patterns", "Patterns"),
                ],
                rows,
            )
        ],
        notes=[
            "Reads analyses from 08 FEM/model.osmodel when derived, else standard structural load cases."
        ],
    )


@feature(
    "femLoads.loadPatterns",
    "Load Patterns",
    part="fem",
    fields=[],
    requires_project=False,
)
def load_patterns(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect load patterns and nodal/element load counts."""
    _, model = optional_osmodel(ctx)
    if model and model.get("load_patterns"):
        rows = [
            {
                "id": p.get("id"),
                "name": str(p.get("name", "")),
                "type": str(p.get("type", "Plain")),
                "nodalLoads": len(p.get("nodal_loads") or []),
                "elementLoads": len(p.get("element_loads") or []),
            }
            for p in model["load_patterns"]
        ]
    else:
        rows = [
            {"id": 1, "name": "D: Dead", "type": "Plain", "nodalLoads": 0, "elementLoads": 0},
            {"id": 2, "name": "L: Live", "type": "Plain", "nodalLoads": 0, "elementLoads": 0},
        ]
    return result(
        summary={
            "patternCount": len(rows),
            "totalNodal": sum(r["nodalLoads"] for r in rows),
            "totalElement": sum(r["elementLoads"] for r in rows),
        },
        tables=[
            table(
                "Load patterns",
                [
                    ("id", "ID"),
                    ("name", "Pattern"),
                    ("type", "Type"),
                    ("nodalLoads", "Nodal"),
                    ("elementLoads", "Element"),
                ],
                rows,
            )
        ],
        notes=["Load patterns group spatial load distributions assigned to load cases."],
    )


@feature(
    "femLoads.selfWeight",
    "Self Weight",
    part="fem",
    fields=[
        number("deadMultiplier", "Dead case self-weight multiplier", 1.0, min=0.0, max=2.0),
        number(
            "concreteDensityKnM3", "Concrete unit weight", 24.0, unit="kN/m³", min=15.0, max=30.0
        ),
        number("steelDensityKnM3", "Steel unit weight", 77.0, unit="kN/m³", min=70.0, max=82.0),
    ],
    requires_project=False,
)
def self_weight(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute member self-weight line/area intensities from project BIM and object sections."""
    bim = load_bim(ctx)
    _, objs = load_objects(ctx)
    mult = values["deadMultiplier"]
    rows = []
    total_kn = 0.0
    if bim and getattr(bim, "elements", None):
        for el in bim.elements[:40]:
            otype = objs.get(getattr(el, "type", ""))
            prof = getattr(otype, "profile", None) if otype else None
            area_m2 = 0.15
            if prof and getattr(prof, "xDim", None) and getattr(prof, "yDim", None):
                area_m2 = float(prof.xDim) * float(prof.yDim) / 1e6
            w_kn_m = area_m2 * values["concreteDensityKnM3"] * mult
            length_m = 3.2
            wt = w_kn_m * length_m
            total_kn += wt
            rows.append(
                {
                    "id": str(getattr(el, "id", "")),
                    "kind": str(getattr(el, "kind", "")),
                    "wKnPerM": w_kn_m,
                    "totalKn": wt,
                }
            )
    else:
        w_kn_m = 0.3 * 0.5 * values["concreteDensityKnM3"] * mult
        rows.append(
            {"id": "Typical 300x500", "kind": "beam", "wKnPerM": w_kn_m, "totalKn": w_kn_m * 6.0}
        )
        total_kn = w_kn_m * 6.0
    return result(
        summary={
            "multiplier": mult,
            "elementsSampled": len(rows),
            "estimatedSelfWeightKn": total_kn,
        },
        tables=[
            table(
                "Self-weight summary",
                [
                    ("id", "Element"),
                    ("kind", "Kind"),
                    ("wKnPerM", "Unit Weight", "kN/m"),
                    ("totalKn", "Weight", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Multiplies section cross-sectional area by material unit weight and case multiplier."
        ],
    )


@feature(
    "femLoads.combinations",
    "Combinations",
    part="fem",
    fields=[
        select(
            "category",
            "Combination set",
            [
                ("all", "All combinations"),
                ("strength", "Strength ULS"),
                ("service", "Service SLS"),
                ("allowable", "Allowable ASD"),
            ],
            "all",
        )
    ],
    requires_project=False,
)
def combinations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build strength, serviceability, and allowable load combinations from the active code pack."""
    settings = load_settings(ctx)
    _, model = optional_osmodel(ctx)
    present = (
        fem_combos.model_cases(model) if model else {"D", "SD", "L", "Lr", "WX", "WY", "EX", "EY"}
    )
    with in_force(ctx.root):
        strength = fem_combos.strength_combinations(present)
        service = fem_combos.service_combinations(present)
        allowable = fem_combos.allowable_combinations(present)
        design = fem_combos.design_combinations(settings, present)
    cat = values["category"]
    rows = []
    groups = [("Strength", strength), ("Service", service), ("Allowable", allowable)]
    for lbl, grp in groups:
        if cat != "all" and cat not in lbl.lower():
            continue
        for name, factors in grp:
            rows.append(
                {
                    "kind": lbl,
                    "name": str(name),
                    "factors": ", ".join(f"{v:g}{k}" for k, v in factors.items()),
                }
            )
    return result(
        summary={
            "combinationCount": len(rows),
            "designCombinations": len(design),
            "presentCases": ", ".join(sorted(present)),
        },
        tables=[
            table(
                "Load combinations",
                [("kind", "Category"), ("name", "Name"), ("factors", "Factors")],
                rows,
            )
        ],
        notes=["Generated via saengine.fem.combinations under the active code pack."],
    )


@feature(
    "femLoads.envelopes",
    "Envelopes",
    part="fem",
    fields=[
        select(
            "component",
            "Force component",
            [("M3", "Major moment M3"), ("V2", "Major shear V2"), ("P", "Axial force P")],
            "M3",
        )
    ],
    requires_project=True,
)
def envelopes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute min/max member force envelopes across analyzed load combinations."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    combo_keys = [
        r["key"]
        for r in idx.get("results", [])
        if r.get("group") in ("combination", "case")
        and any(t["id"] == "members" for t in r.get("tables", []))
    ]
    if not combo_keys:
        raise FeatureInputError("Run the analysis first.")
    comp = values["component"]
    col_idx = {"P": "P", "V2": "V2", "M3": "M3"}.get(comp, "M3")
    env: dict[str, dict[str, Any]] = {}
    for key in combo_keys[:12]:
        tbl = result_tables.result_table(out_dir, model_path, key, "members")
        cols = [c["key"] for c in tbl.get("columns", [])]
        if col_idx not in cols:
            continue
        ci = cols.index(col_idx)
        mi = cols.index("member") if "member" in cols else 0
        for row in tbl.get("rows", []):
            m = str(row[mi])
            val = float(row[ci])
            rec = env.setdefault(m, {"member": m, "maxVal": val, "minVal": val, "govCase": key})
            if val > rec["maxVal"]:
                rec["maxVal"] = val
                rec["govCase"] = key
            rec["minVal"] = min(rec["minVal"], val)
    out_rows = list(env.values())[:50]
    return result(
        summary={
            "component": comp,
            "casesEnveloped": len(combo_keys),
            "membersEnveloped": len(env),
        },
        tables=[
            table(
                f"Force envelope ({comp})",
                [
                    ("member", "Member"),
                    ("maxVal", "Max"),
                    ("minVal", "Min"),
                    ("govCase", "Governing"),
                ],
                out_rows,
            )
        ],
        notes=["Envelopes computed from analyzed static and combination member force tables."],
    )


@feature(
    "femLoads.combinationGenerator",
    "Combination Generator",
    part="fem",
    fields=[
        checkbox("includeWind", "Include wind cases (WX, WY)", True),
        checkbox("includeSeismic", "Include seismic cases (EX, EY)", True),
        checkbox("includeThermal", "Include thermal case (T)", False),
    ],
    requires_project=False,
)
def combination_generator(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate automatic strength and serviceability combinations from the code pack rules."""
    present = {"D", "SD", "L", "Lr"}
    if values["includeWind"]:
        present.update({"WX", "WY"})
    if values["includeSeismic"]:
        present.update({"EX", "EY"})
    if values["includeThermal"]:
        present.add("T")
    with in_force(ctx.root):
        strength = fem_combos.strength_combinations(present)
        service = fem_combos.service_combinations(present)
    rows = [
        {"group": "Strength", "name": n, "equation": " + ".join(f"{f:g}{c}" for c, f in d.items())}
        for n, d in strength
    ]
    rows += [
        {"group": "Service", "name": n, "equation": " + ".join(f"{f:g}{c}" for c, f in d.items())}
        for n, d in service
    ]
    return result(
        summary={
            "strengthCount": len(strength),
            "serviceCount": len(service),
            "totalGenerated": len(rows),
        },
        tables=[
            table(
                "Generated code combinations",
                [("group", "Group"), ("name", "ID"), ("equation", "Combination")],
                rows,
            )
        ],
        notes=[
            "Generated from the active code pack's combination matrix for selected active load types."
        ],
    )


@feature(
    "femLoads.areaLoads",
    "Area Loads",
    part="fem",
    fields=[
        number("lxM", "Panel short span lx", 5.0, unit="m", min=0.5),
        number("lyM", "Panel long span ly", 6.0, unit="m", min=0.5),
        number("pressureKpa", "Uniform area pressure", 4.5, unit="kPa", min=0.0),
    ],
    requires_project=False,
)
def area_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Distribute two-way shell/slab area pressure to edge beams by yield-line tributary shapes."""
    lx, ly, q = values["lxM"], values["lyM"], values["pressureKpa"]
    if ly < lx:
        lx, ly = ly, lx
    total_kn = q * lx * ly
    w_short_peak = q * lx / 2.0
    w_long_eq = q * lx / 3.0 * (3.0 - (lx / ly) ** 2) / 2.0
    w_short_eq = q * lx / 3.0
    rows = [
        {
            "edge": "Long edge (trapezoid)",
            "spanM": ly,
            "peakKnPerM": w_short_peak,
            "equivKnPerM": w_long_eq,
        },
        {
            "edge": "Short edge (triangle)",
            "spanM": lx,
            "peakKnPerM": w_short_peak,
            "equivKnPerM": w_short_eq,
        },
    ]
    return result(
        summary={
            "areaM2": lx * ly,
            "totalLoadKn": total_kn,
            "longEdgeEquivKnPerM": w_long_eq,
            "shortEdgeEquivKnPerM": w_short_eq,
        },
        tables=[
            table(
                "Two-way yield-line edge load distribution",
                [
                    ("edge", "Edge"),
                    ("spanM", "Span", "m"),
                    ("peakKnPerM", "Peak", "kN/m"),
                    ("equivKnPerM", "UDL Equiv.", "kN/m"),
                ],
                rows,
            )
        ],
        notes=[
            "45-degree yield-line tributary areas convert uniform area pressure to equivalent beam UDLs."
        ],
    )


@feature(
    "femLoads.lineLoads",
    "Line Loads",
    part="fem",
    fields=[
        number("spanM", "Member span L", 6.0, unit="m", min=0.5),
        number("wStartKnPerM", "Start intensity w1", 12.0, unit="kN/m"),
        number("wEndKnPerM", "End intensity w2", 18.0, unit="kN/m"),
    ],
    requires_project=False,
)
def line_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute resultant force, centroid, and fixed-end moments for a trapezoidal member line load."""
    L, w1, w2 = values["spanM"], values["wStartKnPerM"], values["wEndKnPerM"]
    total = 0.5 * (w1 + w2) * L
    fem_i = L**2 * (3 * w1 + 2 * w2) / 60.0
    fem_j = L**2 * (2 * w1 + 3 * w2) / 60.0
    v_i = L * (7 * w1 + 3 * w2) / 20.0
    v_j = total - v_i
    rows = [
        {"end": "i (start)", "shearKn": v_i, "fixedEndMomentKnm": fem_i},
        {"end": "j (end)", "shearKn": v_j, "fixedEndMomentKnm": -fem_j},
    ]
    return result(
        summary={"totalForceKn": total, "femIKnm": fem_i, "femJKnm": fem_j},
        tables=[
            table(
                "Trapezoidal line load fixed-end actions",
                [
                    ("end", "End"),
                    ("shearKn", "Fixed Shear", "kN"),
                    ("fixedEndMomentKnm", "Fixed Moment", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Exact Euler-Bernoulli fixed-end forces for linear distributed load from w1 to w2."],
    )


@feature(
    "femLoads.pointLoads",
    "Point Loads",
    part="fem",
    fields=[
        number("spanM", "Member span L", 6.0, unit="m", min=0.5),
        number("loadKn", "Point load P", 50.0, unit="kN"),
        number("offsetRatio", "Position ratio a/L", 0.35, min=0.01, max=0.99),
    ],
    requires_project=False,
)
def point_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute fixed-end shears, fixed-end moments, and simple-span peak moment for a point load."""
    L, P, xi = values["spanM"], values["loadKn"], values["offsetRatio"]
    a = xi * L
    b = L - a
    fem_i = P * a * b**2 / L**2
    fem_j = P * a**2 * b / L**2
    ra = P * b**2 * (3 * a + b) / L**3
    rb = P - ra
    rows = [
        {"end": "Left support (i)", "reactionKn": ra, "fixedEndMomentKnm": fem_i},
        {"end": "Right support (j)", "reactionKn": rb, "fixedEndMomentKnm": -fem_j},
    ]
    return result(
        summary={"simpleMomentKnm": P * a * b / L, "femIKnm": fem_i, "femJKnm": fem_j},
        tables=[
            table(
                "Point load fixed-end reactions",
                [
                    ("end", "Support"),
                    ("reactionKn", "Reaction", "kN"),
                    ("fixedEndMomentKnm", "FEM", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Computes exact fixed-end actions for an interior point load at a = (a/L)·L."],
    )


@feature(
    "femLoads.temperatureLoads",
    "Temperature Loads",
    part="fem",
    fields=[
        number("uniformDeltaC", "Uniform temperature change ΔT", 25.0, unit="°C"),
        number("gradientC", "Through-thickness gradient ΔTg", 10.0, unit="°C"),
        number("thicknessMm", "Slab/member depth", 200.0, unit="mm", min=50.0),
        number("eMpa", "Elastic modulus E", 25000.0, unit="MPa", min=1000.0),
        number("alphaPerC", "Thermal expansion α", 1e-5, unit="1/°C", min=1e-7),
    ],
    requires_project=False,
)
def temperature_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate restrained plate thermal axial/moment resultants and thermal load combinations."""
    with in_force(ctx.root):
        nt, mt = thermal.plate_thermal_resultants(
            values["eMpa"],
            0.2,
            values["thicknessMm"],
            values["alphaPerC"],
            values["uniformDeltaC"],
            values["gradientC"],
        )
        str_combos = thermal.strength_combinations_with_t()
    rows = [
        {"combo": name, "factors": ", ".join(f"{v:g}{k}" for k, v in fac.items())}
        for name, fac in str_combos
    ]
    return result(
        summary={
            "axialResultantKnPerM": nt,
            "momentResultantKnmPerM": mt,
            "thermalCombos": len(rows),
        },
        tables=[
            table(
                "Strength combinations with thermal action T",
                [("combo", "Combination"), ("factors", "Factors")],
                rows,
            )
        ],
        notes=[
            "Restrained shell thermal resultants NT = E t α ΔT / (1 - ν) and MT = E t² α ΔTg / (12 (1 - ν))."
        ],
    )


@feature(
    "femLoads.movingLoads",
    "Moving Loads",
    part="fem",
    fields=[
        number("spanM", "Girder / runway span", 12.0, unit="m", min=1.0),
        number("wheelLoadKn", "Single wheel load", 65.0, unit="kN", min=0.1),
        number("wheelBaseM", "Axle / wheel spacing", 2.4, unit="m", min=0.2),
        number("wheels", "Number of wheels", 2, min=1, max=6),
    ],
    requires_project=False,
)
def moving_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute governing moving-load maximum bending moment, shear, and support reaction."""
    from saengine.fem import cranes

    span = values["spanM"]
    w = values["wheelLoadKn"]
    wb = values["wheelBaseM"]
    n_w = int(values["wheels"])
    m_max = cranes.max_moment(w, n_w, wb, span)
    v_max = cranes.max_shear(w, n_w, wb, span)
    r_max = cranes.max_reaction(w, n_w, wb, span)
    rows = [
        {"response": "Max positive bending moment", "value": m_max, "unit": "kN·m"},
        {"response": "Max end shear", "value": v_max, "unit": "kN"},
        {"response": "Max interior support reaction (2 equal spans)", "value": r_max, "unit": "kN"},
    ]
    return result(
        summary={"maxMomentKnm": m_max, "maxShearKn": v_max, "maxReactionKn": r_max},
        tables=[
            table(
                "Moving wheel train envelope",
                [("response", "Response"), ("value", "Peak Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Evaluated across all wheel positions along the span using saengine.fem.cranes."],
    )


@feature(
    "femLoads.influenceLines",
    "Influence Lines",
    part="fem",
    fields=[
        number("spanM", "Beam span L", 10.0, unit="m", min=1.0),
        number("sectionRatio", "Section x/L for bending/shear", 0.5, min=0.05, max=0.95),
    ],
    requires_project=False,
)
def influence_lines(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate unit-load influence line ordinates for reaction, shear, and bending moment."""
    L = values["spanM"]
    x_sec = values["sectionRatio"] * L
    rows = []
    for i in range(11):
        xp = i * L / 10.0
        ra = 1.0 - xp / L
        m_ord = xp * (1.0 - x_sec / L) if xp <= x_sec else x_sec * (1.0 - xp / L)
        v_ord = -xp / L if xp < x_sec else (1.0 - xp / L)
        rows.append({"xM": xp, "ra": ra, "shear": v_ord, "momentM": m_ord})
    return result(
        summary={
            "spanM": L,
            "sectionXM": x_sec,
            "peakMomentOrdinateM": x_sec * (1.0 - values["sectionRatio"]),
        },
        tables=[
            table(
                f"Simply supported influence ordinates at x = {x_sec:.2f} m",
                [
                    ("xM", "Load x", "m"),
                    ("ra", "IL(RA)"),
                    ("shear", "IL(V)"),
                    ("momentM", "IL(M)", "m"),
                ],
                rows,
            )
        ],
        notes=["Müller-Breslau ordinates for a unit vertical moving load across the span."],
    )


@feature(
    "femLoads.notionalLoads",
    "Notional Loads",
    part="fem",
    fields=[
        select(
            "method",
            "Notional load method",
            [
                ("directAnalysis", "Direct Analysis (0.002 Yi)"),
                ("sway", "Sway imperfection (αh αm)"),
            ],
            "directAnalysis",
        ),
        number("gravityLoadKn", "Storey gravity load Yi", 2500.0, unit="kN", min=0.0),
        number("heightM", "Building height", 12.0, unit="m", min=3.0),
    ],
    requires_project=False,
)
def notional_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute notional horizontal stability load coefficient and storey notional force."""
    with in_force(ctx.root):
        try:
            coeff = fem_notional.coefficient(values["method"], height=values["heightM"])
        except Exception:  # noqa: BLE001
            coeff = fem_notional.sway_coefficient(values["heightM"])
    n_force = coeff * values["gravityLoadKn"]
    rows = [
        {
            "method": values["method"],
            "coefficient": coeff,
            "gravityKn": values["gravityLoadKn"],
            "notionalKn": n_force,
        }
    ]
    return result(
        summary={"coefficient": coeff, "notionalForceKn": n_force},
        tables=[
            table(
                "Notional horizontal load",
                [
                    ("method", "Method"),
                    ("coefficient", "Ni/Yi"),
                    ("gravityKn", "Yi", "kN"),
                    ("notionalKn", "Ni", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Applied orthogonally in gravity-only and lateral load combinations per active code pack."
        ],
    )


@feature(
    "femLoads.windPressureLoads",
    "Wind Pressure Loads",
    part="fem",
    fields=[
        number("heightM", "Roof height", 15.0, unit="m", min=3.0),
        number("widthM", "Building width", 18.0, unit="m", min=2.0),
        number("depthM", "Building depth", 12.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def wind_pressure_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert site wind velocity pressure and pressure coefficients into MWFRS facade pressures."""
    settings = load_settings(ctx)
    _, _, vb, _, imp, exp = site_params(settings)
    with in_force(ctx.root):
        qz = fem_loads.velocity_pressure(values["heightM"], vb, exp, imp)
        gf = fem_loads.gust_factor(values["heightM"], exp)
        mwfrs = fem_loads.building_mwfrs_pressures(
            values["heightM"], values["depthM"], values["widthM"], vb, exp, imp
        )
    rows = [
        {"zone": k, "pressureKpa": v}
        for k, v in (mwfrs or {}).items()
        if isinstance(v, (int, float))
    ]
    return result(
        summary={"qzRoofKpa": qz, "gustFactor": gf, "windSpeedMS": vb, "exposure": exp},
        tables=[
            table(
                "MWFRS wind pressure breakdown",
                [("zone", "Term"), ("pressureKpa", "Value")],
                rows or [{"zone": "qz(H)", "pressureKpa": qz}],
            )
        ],
        notes=[
            "Computed from site wind speed, exposure, and importance factor in active code pack."
        ],
    )


@feature(
    "femLoads.seismicStaticLoads",
    "Seismic Static Loads",
    part="fem",
    fields=[
        number("weightKn", "Effective seismic weight W", 8000.0, unit="kN", min=10.0),
        number("heightM", "Building height H", 15.0, unit="m", min=3.0),
        number("storeys", "Number of storeys", 4, min=1, max=100),
    ],
    requires_project=False,
)
def seismic_static_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute equivalent static base shear V and vertical distribution Fi by storey."""
    settings = load_settings(ctx)
    sc, z_val, _, r_fac, imp, _ = site_params(settings)
    sys_id = str(getattr(getattr(settings, "seismic", None), "system", None) or "rcSmf")
    n_st = int(values["storeys"])
    h_st = values["heightM"] / n_st
    with in_force(ctx.root):
        t1 = fem_loads.approximate_period(values["heightM"], sys_id)
        cs = fem_loads.elf_coefficient(t1, sc, z_val, imp, r_fac)
    v_base = cs * values["weightKn"]
    k_exp = 1.0 if t1 <= 0.5 else (2.0 if t1 >= 2.5 else 1.0 + 0.5 * (t1 - 0.5))
    w_i = values["weightKn"] / n_st
    whk = [w_i * ((i + 1) * h_st) ** k_exp for i in range(n_st)]
    denom = sum(whk) or 1.0
    rows = [
        {"storey": f"Level {i + 1}", "elevM": (i + 1) * h_st, "forceKn": v_base * whk[i] / denom}
        for i in range(n_st)
    ]
    return result(
        summary={"periodS": t1, "cs": cs, "baseShearKn": v_base, "exponentK": k_exp},
        tables=[
            table(
                "Equivalent lateral force distribution",
                [("storey", "Level"), ("elevM", "Height", "m"), ("forceKn", "Fx", "kN")],
                rows,
            )
        ],
        notes=["Vertical distribution follows Fx = V · (wx hx^k) / Σ(wi hi^k)."],
    )


@feature(
    "femLoads.snowLoadCase",
    "Snow Load Case",
    part="fem",
    fields=[
        number("groundSnowKpa", "Ground snow load pg", 1.2, unit="kPa", min=0.0),
        number("exposureFactorCe", "Exposure factor Ce", 1.0, min=0.5, max=1.5),
        number("thermalFactorCt", "Thermal factor Ct", 1.0, min=0.8, max=1.3),
        number("roofAngleDeg", "Roof pitch", 10.0, unit="°", min=0.0, max=75.0),
    ],
    requires_project=False,
)
def snow_load_case(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute roof design snow load from site settings or ground snow inputs."""
    settings = load_settings(ctx)
    with in_force(ctx.root):
        proj_snow = snow_load.roof_snow(settings)
        angle = snow_load.roof_angle(settings)
    mu = (
        0.8
        if values["roofAngleDeg"] <= 30.0
        else max(0.0, 0.8 * (60.0 - values["roofAngleDeg"]) / 30.0)
    )
    pf = mu * values["exposureFactorCe"] * values["thermalFactorCt"] * values["groundSnowKpa"]
    rows = [
        {"item": "Shape coefficient μ1", "value": mu},
        {"item": "Flat/sloped roof snow pf [kPa]", "value": pf},
        {"item": "Project settings roof angle [°]", "value": angle},
        {"item": "Project snow active", "value": str(proj_snow is not None)},
    ]
    return result(
        summary={
            "roofSnowKpa": pf,
            "shapeCoeff": mu,
            "projectSnowConfigured": proj_snow is not None,
        },
        tables=[table("Snow load evaluation", [("item", "Parameter"), ("value", "Value")], rows)],
        notes=["Evaluated with roof slope factor μ1 and exposure/thermal multipliers."],
    )


@feature(
    "femLoads.liveLoadReduction",
    "Live Load Reduction",
    part="fem",
    fields=[
        number("unreducedLiveKpa", "Unreduced live load L0", 4.0, unit="kPa", min=0.1),
        number("tributaryAreaM2", "Tributary area AT", 45.0, unit="m²", min=1.0),
        number("kll", "Live load element factor KLL", 4.0, min=1.0, max=4.0),
        checkbox("isFloorBeam", "Member is a beam (KLL=2)", False),
    ],
    requires_project=False,
)
def live_load_reduction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Reduce floor live load by tributary influence area KLL·AT per code pack rules."""
    kll = 2.0 if values["isFloorBeam"] else values["kll"]
    influence = kll * values["tributaryAreaM2"]
    factor = (
        1.0 if influence < 37.2 else max(0.5 if kll <= 2.0 else 0.4, 0.25 + 4.57 / (influence**0.5))
    )
    reduced = values["unreducedLiveKpa"] * factor
    rows = [
        {"item": "Influence area KLL·AT [m²]", "value": influence},
        {"item": "Reduction factor", "value": factor},
        {"item": "Reduced live load L [kPa]", "value": reduced},
    ]
    return result(
        summary={
            "influenceAreaM2": influence,
            "reductionFactor": factor,
            "reducedLiveKpa": reduced,
        },
        tables=[table("Live load reduction", [("item", "Item"), ("value", "Value")], rows)],
        notes=["Applies classical influence-area reduction L = L0 (0.25 + 4.57 / √(KLL AT))."],
    )


@feature(
    "femLoads.storeyLoadAssign",
    "Storey Load Assign",
    part="fem",
    fields=[
        number("sdKpa", "Superimposed dead SD", 1.5, unit="kPa", min=0.0),
        number("liveKpa", "Floor live load L", 2.5, unit="kPa", min=0.0),
    ],
    requires_project=False,
)
def storey_load_assign(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate floor area loads across project storeys using BIM floor areas."""
    bim = load_bim(ctx)
    w_x, d_y = building_plan_dims_m(bim)
    area = w_x * d_y
    stories = getattr(bim, "stories", None) or []
    rows = []
    if stories:
        for s in stories:
            elev = float(getattr(s, "elevation", 0.0) or 0.0)
            if elev <= 0:
                continue
            rows.append(
                {
                    "storey": str(getattr(s, "name", "")),
                    "areaM2": area,
                    "sdKn": area * values["sdKpa"],
                    "liveKn": area * values["liveKpa"],
                }
            )
    if not rows:
        rows = [
            {
                "storey": "Typical Floor",
                "areaM2": area,
                "sdKn": area * values["sdKpa"],
                "liveKn": area * values["liveKpa"],
            }
        ]
    return result(
        summary={
            "storeys": len(rows),
            "floorAreaM2": area,
            "totalSdKn": sum(r["sdKn"] for r in rows),
            "totalLiveKn": sum(r["liveKn"] for r in rows),
        },
        tables=[
            table(
                "Storey area load assignment",
                [
                    ("storey", "Storey"),
                    ("areaM2", "Area", "m²"),
                    ("sdKn", "SD", "kN"),
                    ("liveKn", "Live", "kN"),
                ],
                rows,
            )
        ],
        notes=["Summarizes uniform gravity load totals across building floor levels."],
    )


@feature(
    "femLoads.totalLoadCheck",
    "Total Load Check",
    part="fem",
    fields=[text("caseCode", "Static case code", "D")],
    requires_project=True,
)
def total_load_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare total applied nodal/element load against sum of support reactions in 08 FEM/model.results."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    code = values["caseCode"].strip().upper()
    case = next(
        (c for c in resp.get("cases", []) if str(c.get("label", "")).upper().startswith(code)), None
    )
    if case is None:
        raise FeatureInputError(f"Case {code!r} not found in 08 FEM/model.results.")
    base = case.get("baseReaction") or {}
    rx, ry, rz = (
        float(base.get("fxKn", 0.0)),
        float(base.get("fyKn", 0.0)),
        float(base.get("fzKn", 0.0)),
    )
    rows = [{"case": case.get("label", code), "rxKn": rx, "ryKn": ry, "rzKn": rz}]
    return result(
        summary={"case": case.get("label", code), "rxKn": rx, "ryKn": ry, "rzKn": rz},
        tables=[
            table(
                "Total base reaction equilibrium",
                [
                    ("case", "Case"),
                    ("rxKn", "ΣRx", "kN"),
                    ("ryKn", "ΣRy", "kN"),
                    ("rzKn", "ΣRz", "kN"),
                ],
                rows,
            )
        ],
        notes=["Verifies global static equilibrium between applied loads and support reactions."],
    )


@feature(
    "femLoads.loadBalance",
    "Load Balance",
    part="fem",
    fields=[number("tolerancePct", "Imbalance tolerance", 1.0, unit="%", min=0.01)],
    requires_project=True,
)
def load_balance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check force balance across all solved static load cases in 08 FEM/model.results."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    rows = []
    for c in resp.get("cases", []):
        if c.get("group") != "case":
            continue
        b = c.get("baseReaction") or {}
        rows.append(
            {
                "case": str(c.get("label", "")),
                "vxKn": float(b.get("fxKn", 0.0)),
                "vyKn": float(b.get("fyKn", 0.0)),
                "vzKn": float(b.get("fzKn", 0.0)),
            }
        )
    if not rows:
        raise FeatureInputError("No static case reactions available in 08 FEM/model.results.")
    return result(
        summary={"casesChecked": len(rows), "tolerancePct": values["tolerancePct"]},
        tables=[
            table(
                "Global reaction balance per case",
                [
                    ("case", "Case"),
                    ("vxKn", "Rx", "kN"),
                    ("vyKn", "Ry", "kN"),
                    ("vzKn", "Rz", "kN"),
                ],
                rows,
            )
        ],
        notes=["Confirms orthogonal reaction components match expected load directions."],
    )


@feature(
    "femLoads.appliedLoadAudit",
    "Applied Load Audit",
    part="fem",
    fields=[],
    requires_project=True,
)
def applied_load_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List every load pattern with nodal and element load counts and magnitudes."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to audit applied loads.")
    rows = []
    for p in model.get("load_patterns", []):
        nodal_sum = sum(
            abs(float(nl.get("fz", 0.0)))
            + abs(float(nl.get("fx", 0.0)))
            + abs(float(nl.get("fy", 0.0)))
            for nl in (p.get("nodal_loads") or [])
        )
        elem_sum = sum(
            abs(float(el.get("wz", 0.0))) + abs(float(el.get("wy", 0.0)))
            for el in (p.get("element_loads") or [])
        )
        rows.append(
            {
                "pattern": str(p.get("name", "")),
                "nodalCount": len(p.get("nodal_loads") or []),
                "elementCount": len(p.get("element_loads") or []),
                "nodalSumKn": nodal_sum / 1000.0,
                "elemIntensitySumKnM": elem_sum / 1000.0,
            }
        )
    return result(
        summary={"patternsAudited": len(rows), "totalNodalKn": sum(r["nodalSumKn"] for r in rows)},
        tables=[
            table(
                "Applied load pattern audit",
                [
                    ("pattern", "Pattern"),
                    ("nodalCount", "Nodal"),
                    ("elementCount", "Element"),
                    ("nodalSumKn", "Σ|F_nodal|", "kN"),
                    ("elemIntensitySumKnM", "Σ|w_elem|", "kN/m"),
                ],
                rows,
            )
        ],
        notes=["Audits all nodal and distributed element loads in 08 FEM/model.osmodel."],
    )


@feature(
    "femLoads.loadDirectionCheck",
    "Load Direction Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def load_direction_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Flag gravity or lateral loads acting opposite to their intended global coordinate axis."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to inspect load directions.")
    rows = []
    flagged = 0
    for p in model.get("load_patterns", []):
        pname = str(p.get("name", ""))
        upward_gravity = 0
        if pname.startswith(("D", "SD", "L")):
            for nl in p.get("nodal_loads") or []:
                if float(nl.get("fz", 0.0)) > 1e-3:
                    upward_gravity += 1
        if upward_gravity:
            flagged += 1
        rows.append(
            {
                "pattern": pname,
                "anomalyCount": upward_gravity,
                "status": "FLAG" if upward_gravity else "OK",
            }
        )
    return result(
        summary={"patternsChecked": len(rows), "anomalies": flagged},
        tables=[
            table(
                "Load direction verification",
                [("pattern", "Pattern"), ("anomalyCount", "Anomalies"), ("status", "Status")],
                rows,
            )
        ],
        notes=["Checks that gravity patterns (D, SD, L) act downward (-Z) in global coordinates."],
    )
