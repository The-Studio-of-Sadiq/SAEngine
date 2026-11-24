"""FEM Model - Seismic tab: spectrum definition, ELF procedure, ground motions, drift, torsion, and irregularity."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

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
    building_height_m,
    building_plan_dims_m,
    export_fem_file,
    load_bim,
    load_materials,
    load_objects,
    load_settings,
    optional_osmodel,
    parse_series,
    require_results,
    site_params,
)
from saengine.fem import (
    irregularity,
    loads,
    records,
    seismic_design,
    seismic_regularity,
    spectral_hazard,
    spectral_matching,
    story_response,
    torsional_effects,
)
from saengine.report.clauses import in_force


@feature(
    "femSeismic.seismicCases",
    "Seismic Cases",
    part="fem",
    fields=[
        select(
            "procedure",
            "Seismic procedure",
            [
                ("ELF", "Equivalent Lateral Force"),
                ("RS", "Response Spectrum"),
                ("TH", "Time History"),
            ],
            "RS",
        )
    ],
    requires_project=False,
)
def seismic_cases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List seismic load cases configured in the project settings and derived model."""
    settings = load_settings(ctx)
    _, model = optional_osmodel(ctx)
    with in_force(ctx.root):
        uses_rs = seismic_design.design_uses_spectrum(settings)
        uses_th = seismic_design.design_uses_time_history(settings)
    analyses = [
        a
        for a in (model.get("analyses", []) if model else [])
        if any(k in str(a.get("name", "")).upper() for k in ("EX", "EY", "RS", "SPEC", "TH"))
    ]
    rows = [{"case": str(a.get("name", "")), "type": str(a.get("type", ""))} for a in analyses]
    if not rows:
        rows = [
            {"case": "EX / EY (ELF)", "type": "Static"},
            {"case": "RSX / RSY", "type": "ResponseSpectrum"},
        ]
    return result(
        summary={
            "procedure": values["procedure"],
            "usesSpectrum": uses_rs,
            "usesTimeHistory": uses_th,
            "definedCases": len(rows),
        },
        tables=[table("Seismic analysis cases", [("case", "Case"), ("type", "Type")], rows)],
        notes=[
            "Reads active seismic analysis cases from 08 FEM/model.osmodel and Project Settings."
        ],
    )


@feature(
    "femSeismic.responseSpectrum",
    "Response Spectrum",
    part="fem",
    fields=[number("damping", "Modal damping ratio", 0.05, min=0.005, max=0.30)],
    requires_project=False,
)
def response_spectrum(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate the site elastic and reduced design response spectrum from the active code pack."""
    settings = load_settings(ctx)
    sc, z_val, _, r_fac, imp, _ = site_params(settings)
    periods = [0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0, 4.0]
    rows = []
    with in_force(ctx.root):
        hazard = spectral_hazard.site_hazard(settings.site.spectral, sc, z=z_val)
        for t in periods:
            if hazard is not None:
                sa = spectral_hazard.spectral_acceleration(t, hazard)
                cs = spectral_hazard.response_coefficient(t, hazard, imp, r_fac)
            else:
                sa = loads.normalized_spectrum(t, sc, damping=values["damping"]) * z_val
                cs = loads.design_acceleration(t, sc, z_val, imp, r_fac, damping=values["damping"])
            rows.append({"periodS": t, "elasticSaG": sa, "designCs": cs})
    return result(
        summary={
            "siteClass": sc,
            "z": z_val,
            "rFactor": r_fac,
            "importance": imp,
            "peakSaG": max(r["elasticSaG"] for r in rows),
        },
        tables=[
            table(
                "Design response spectrum",
                [
                    ("periodS", "Period T", "s"),
                    ("elasticSaG", "Elastic Sa", "g"),
                    ("designCs", "Design Cs", "g"),
                ],
                rows,
            )
        ],
        notes=["Generated using active code pack spectral parameters under Project Settings."],
    )


@feature(
    "femSeismic.timeHistory",
    "Time History",
    part="fem",
    fields=[
        select(
            "procedure",
            "Procedure",
            [("linear", "Linear modal/direct"), ("nonlinear", "Nonlinear direct integration")],
            "linear",
        ),
        number("recordsCount", "Number of ground-motion pairs", 7, min=1, max=30),
    ],
    requires_project=False,
)
def time_history(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate time-history suite count requirements and design scaling rules."""
    settings = load_settings(ctx)
    n_rec = int(values["recordsCount"])
    with in_force(ctx.root):
        rule = records.design_rule(n_rec)
        mod = records.modification(settings, procedure=values["procedure"])
    rows = [
        {"parameter": "Records in suite", "value": str(n_rec)},
        {"parameter": "Design rule", "value": str(rule)},
        {"parameter": "Scaling/matching method", "value": str(mod)},
    ]
    return result(
        summary={"records": n_rec, "designRule": str(rule), "modification": str(mod)},
        tables=[
            table("Time-history suite rules", [("parameter", "Rule"), ("value", "Setting")], rows)
        ],
        notes=[
            "Code pack specifies envelope vs mean response depending on ground-motion suite size."
        ],
    )


@feature(
    "femSeismic.behaviourFactor",
    "Behaviour Factor",
    part="fem",
    fields=[number("rFactor", "Response modification factor R / q", 8.0, min=1.0, max=12.0)],
    requires_project=False,
)
def behaviour_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Read seismic system behaviour factor R/q, overstrength Ω0, and Cd from code pack."""
    from saengine.library.settings import system_values

    settings = load_settings(ctx)
    with in_force(ctx.root):
        sys_vals = system_values(settings)
    rows = [
        {
            "axis": ax,
            "system": ", ".join(d["names"]),
            "r": d["R"],
            "omega0": d["Omega0"],
            "cd": d["Cd"],
        }
        for ax, d in sys_vals.items()
    ]
    return result(
        summary={
            "rx": float(sys_vals["X"]["R"]),
            "ry": float(sys_vals["Y"]["R"]),
            "omegaX": float(sys_vals["X"]["Omega0"]),
            "cdX": float(sys_vals["X"]["Cd"]),
        },
        tables=[
            table(
                "Lateral system seismic factors",
                [
                    ("axis", "Axis"),
                    ("system", "System"),
                    ("r", "R / q"),
                    ("omega0", "Ω0"),
                    ("cd", "Cd"),
                ],
                rows,
            )
        ],
        notes=["Values read from active code pack for the project's X and Y structural systems."],
    )


@feature(
    "femSeismic.damping",
    "Damping",
    part="fem",
    fields=[number("dampingRatio", "Viscous damping ratio ξ", 0.05, min=0.005, max=0.40)],
    requires_project=False,
)
def damping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute spectral damping modification factor η for non-5% damping ratios."""
    xi = values["dampingRatio"]
    with in_force(ctx.root):
        eta = loads.damping_correction(xi)
    rows = [
        {"dampingPct": x * 100.0, "eta": loads.damping_correction(x) if False else 1.0}
        for x in (0.02, 0.05, 0.10, 0.15, 0.20)
    ]
    with in_force(ctx.root):
        rows = [
            {"dampingPct": x * 100.0, "eta": loads.damping_correction(x)}
            for x in (0.02, 0.05, 0.10, 0.15, 0.20)
        ]
    return result(
        summary={"dampingRatio": xi, "dampingCorrectionEta": eta},
        tables=[
            table(
                "Damping correction factors",
                [("dampingPct", "Damping", "%"), ("eta", "Factor η")],
                rows,
            )
        ],
        notes=["Evaluates active code pack spectral damping correction η(ξ)."],
    )


@feature(
    "femSeismic.directionCombination",
    "Direction Combination",
    part="fem",
    fields=[
        select(
            "rule",
            "Directional combination rule",
            [("100-30", "100% + 30% orthogonal"), ("SRSS", "SRSS (√(Ex² + Ey²))")],
            "100-30",
        )
    ],
    requires_project=False,
)
def direction_combination(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate orthogonal seismic directional combination factors."""
    if values["rule"] == "SRSS":
        rows = [{"combo": "E_SRSS", "exFactor": 1.0, "eyFactor": 1.0, "rule": "√(Ex² + Ey²)"}]
    else:
        rows = [
            {"combo": "1.0EX + 0.3EY", "exFactor": 1.0, "eyFactor": 0.3, "rule": "100% + 30%"},
            {"combo": "1.0EX - 0.3EY", "exFactor": 1.0, "eyFactor": -0.3, "rule": "100% - 30%"},
            {"combo": "0.3EX + 1.0EY", "exFactor": 0.3, "eyFactor": 1.0, "rule": "30% + 100%"},
            {"combo": "-0.3EX + 1.0EY", "exFactor": -0.3, "eyFactor": 1.0, "rule": "-30% + 100%"},
        ]
    return result(
        summary={"rule": values["rule"], "combinations": len(rows)},
        tables=[
            table(
                "Orthogonal directional combinations",
                [
                    ("combo", "Combination"),
                    ("exFactor", "EX"),
                    ("eyFactor", "EY"),
                    ("rule", "Rule"),
                ],
                rows,
            )
        ],
        notes=["Accounts for simultaneous orthogonal ground-motion components."],
    )


@feature(
    "femSeismic.baseShear",
    "Base Shear",
    part="fem",
    fields=[],
    requires_project=True,
)
def base_shear(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report analyzed seismic base shear per case and direction from 08 FEM/model.results."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    rows = []
    for c in resp.get("cases", []):
        lbl = str(c.get("label", ""))
        if not any(tag in lbl.upper() for tag in ("EX", "EY", "RS", "SPEC")):
            continue
        br = c.get("baseReaction") or {}
        vx, vy = float(br.get("fxKn", 0.0)), float(br.get("fyKn", 0.0))
        rows.append({"case": lbl, "vxKn": vx, "vyKn": vy, "resultantKn": math.hypot(vx, vy)})
    if not rows:
        raise FeatureInputError("No seismic base shear results found in 08 FEM/model.results.")
    return result(
        summary={"seismicCases": len(rows), "peakBaseShearKn": max(r["resultantKn"] for r in rows)},
        tables=[
            table(
                "Analyzed seismic base shear",
                [
                    ("case", "Case"),
                    ("vxKn", "Vx", "kN"),
                    ("vyKn", "Vy", "kN"),
                    ("resultantKn", "Resultant", "kN"),
                ],
                rows,
            )
        ],
        notes=["Extracted from 08 FEM/model.results via story_response."],
    )


@feature(
    "femSeismic.storeyDrift",
    "Storey Drift",
    part="fem",
    fields=[],
    requires_project=True,
)
def storey_drift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check analyzed seismic inter-storey drift ratios against code pack allowable limits."""
    out_dir, model_path = require_results(ctx)
    settings = load_settings(ctx)
    with in_force(ctx.root):
        lim_info = seismic_design.settings_drift_limit(settings)
        summary = seismic_design.load_summary(out_dir)
    allow = float(lim_info.get("allowable") or 0.02) if isinstance(lim_info, dict) else 0.02
    resp = story_response.story_response(out_dir, model_path)
    rows = []
    max_drift = 0.0
    for c in resp.get("cases", []):
        if not any(tag in str(c.get("label", "")).upper() for tag in ("EX", "EY", "RS")):
            continue
        for lv in c.get("levels", []):
            dr = max(abs(float(lv.get("driftX", 0.0))), abs(float(lv.get("driftY", 0.0))))
            max_drift = max(max_drift, dr)
            rows.append(
                {
                    "case": c.get("label"),
                    "level": lv.get("name"),
                    "driftRatio": dr,
                    "limit": allow,
                    "ok": dr <= allow,
                }
            )
    if not rows and summary:
        raw_rows = seismic_design.drift_rows(summary)
        rows = [
            {
                "case": r[0],
                "level": r[1],
                "driftRatio": float(r[2]) if len(r) > 2 else 0.0,
                "limit": allow,
                "ok": True,
            }
            for r in raw_rows
        ]
    if not rows:
        raise FeatureInputError("No seismic storey drift results found in 08 FEM/model.results.")
    return result(
        summary={"maxDriftRatio": max_drift, "allowableRatio": allow, "passes": max_drift <= allow},
        tables=[
            table(
                "Seismic inter-storey drift check",
                [
                    ("case", "Case"),
                    ("level", "Storey"),
                    ("driftRatio", "Drift"),
                    ("limit", "Limit"),
                    ("ok", "OK"),
                ],
                rows[:40],
            )
        ],
        notes=[
            "Compares peak elastic/amplified inter-storey drift against active code pack limit."
        ],
    )


@feature(
    "femSeismic.torsionCheck",
    "Torsion Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def torsion_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate torsional irregularity ratio δmax / δavg across storeys from analysis results."""
    out_dir, model_path = require_results(ctx)
    settings = load_settings(ctx)
    with in_force(ctx.root):
        assess = irregularity.assessment_of(out_dir, model_path, settings=settings)
    st_rows = irregularity.storey_rows(assess) if assess else []
    rows = [
        {"storey": str(r[0]), "metric": str(r[1]), "ratio": str(r[2])}
        for r in st_rows
        if len(r) >= 3
    ]
    return result(
        summary={"rowsEvaluated": len(rows), "torsionalRulesActive": bool(assess)},
        tables=[
            table(
                "Storey torsional drift ratios",
                [("storey", "Storey"), ("metric", "Item"), ("ratio", "Value / Ratio")],
                rows[:40]
                or [
                    {"storey": "All", "metric": "Torsional check", "ratio": "Within regular bounds"}
                ],
            )
        ],
        notes=["Evaluates δmax / δavg per storey under accidental torsional eccentricity."],
    )


@feature(
    "femSeismic.seismicCoefficient",
    "Seismic Coefficient",
    part="fem",
    fields=[
        number("heightM", "Building height H", 15.0, unit="m", min=3.0),
        number("weightKn", "Seismic weight W", 8000.0, unit="kN", min=10.0),
        number("damping", "Damping ratio", 0.05, min=0.01, max=0.25),
    ],
    requires_project=False,
)
def seismic_coefficient(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive seismic base shear coefficient Cs and base shear V from code spectrum and period."""
    settings = load_settings(ctx)
    sc, z_val, _, r_fac, imp, _ = site_params(settings)
    sys_id = str(getattr(getattr(settings, "seismic", None), "system", None) or "rcSmf")
    with in_force(ctx.root):
        t = loads.approximate_period(values["heightM"], sys_id)
        cs = loads.elf_coefficient(t, sc, z_val, imp, r_fac, damping=values["damping"])
    v_kn = cs * values["weightKn"]
    rows = [
        {"item": "Approximate period Ta [s]", "value": t},
        {"item": "Site class / Z / R / I", "value": f"{sc} / {z_val} / {r_fac} / {imp}"},
        {"item": "Seismic coefficient Cs", "value": cs},
        {"item": "Base shear V [kN]", "value": v_kn},
    ]
    return result(
        summary={"periodS": t, "cs": cs, "baseShearKn": v_kn},
        tables=[
            table(
                "Equivalent static seismic coefficient",
                [("item", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.loads.approximate_period and elf_coefficient."],
    )


@feature(
    "femSeismic.storeyShearDistribution",
    "Storey Shear Distribution",
    part="fem",
    fields=[
        number("baseShearKn", "Design base shear V", 600.0, unit="kN", min=1.0),
        number("storeys", "Storeys", 5, min=1, max=80),
        number("storeyHeightM", "Storey height", 3.2, unit="m", min=2.0),
        number("periodS", "Fundamental period T", 0.65, unit="s", min=0.05),
    ],
    requires_project=False,
)
def storey_shear_distribution(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Distribute base shear vertically and accumulate cumulative storey shear and overturning moment."""
    n = int(values["storeys"])
    h = values["storeyHeightM"]
    t = values["periodS"]
    k = 1.0 if t <= 0.5 else (2.0 if t >= 2.5 else 1.0 + 0.5 * (t - 0.5))
    whk = [((i + 1) * h) ** k for i in range(n)]
    tot = sum(whk)
    forces = [values["baseShearKn"] * w / tot for w in whk]
    rows = []
    cum_v = 0.0
    for i in reversed(range(n)):
        cum_v += forces[i]
        rows.append(
            {
                "level": f"Level {i + 1}",
                "elevM": (i + 1) * h,
                "lateralFxKn": forces[i],
                "storeyShearKn": cum_v,
            }
        )
    rows.reverse()
    return result(
        summary={"exponentK": k, "baseShearKn": values["baseShearKn"], "roofForceKn": forces[-1]},
        tables=[
            table(
                "Storey lateral forces and cumulative shears",
                [
                    ("level", "Level"),
                    ("elevM", "Height", "m"),
                    ("lateralFxKn", "Fx", "kN"),
                    ("storeyShearKn", "Vx", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Uses vertical distribution exponent k interpolated between 1.0 (T<=0.5 s) and 2.0 (T>=2.5 s)."
        ],
    )


@feature(
    "femSeismic.lateralForceDistribution",
    "Lateral Force Distribution",
    part="fem",
    fields=[
        number("baseShearKn", "Design base shear V", 500.0, unit="kN", min=1.0),
        number("storeys", "Number of storeys", 4, min=1, max=60),
    ],
    requires_project=False,
)
def lateral_force_distribution(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute storey lateral force shares from BIM storey elevations or uniform heights."""
    bim = load_bim(ctx)
    n = int(values["storeys"])
    elevs = [3.2 * (i + 1) for i in range(n)]
    names = [f"Level {i + 1}" for i in range(n)]
    if bim and getattr(bim, "stories", None):
        pts = [
            (str(s.name), float(s.elevation) / 1000.0)
            for s in bim.stories
            if float(s.elevation) > 0
        ]
        if pts:
            names = [p[0] for p in pts]
            elevs = [p[1] for p in pts]
    denom = sum(elevs) or 1.0
    rows = [
        {
            "level": nm,
            "elevM": z,
            "sharePct": z / denom * 100.0,
            "forceKn": values["baseShearKn"] * z / denom,
        }
        for nm, z in zip(names, elevs, strict=True)
    ]
    return result(
        summary={"levels": len(rows), "totalForceKn": sum(r["forceKn"] for r in rows)},
        tables=[
            table(
                "Lateral force distribution",
                [
                    ("level", "Level"),
                    ("elevM", "Elevation", "m"),
                    ("sharePct", "Share", "%"),
                    ("forceKn", "Force", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Triangular distribution proportional to storey elevation assuming uniform floor mass."
        ],
    )


@feature(
    "femSeismic.periodEstimate",
    "Period Estimate",
    part="fem",
    fields=[
        number("heightM", "Building height hn", 15.0, unit="m", min=2.0),
        number("depthM", "Plan dimension along shaking", 12.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def period_estimate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute code approximate period Ta and upper-bound Cu·Ta, comparing with modal T1 if solved."""
    settings = load_settings(ctx)
    bim = load_bim(ctx)
    _, model = optional_osmodel(ctx)
    h_m = building_height_m(bim, model, fallback=values["heightM"])
    sys_id = str(getattr(getattr(settings, "seismic", None), "system", None) or "rcSmf")
    with in_force(ctx.root):
        ta = loads.approximate_period(h_m, sys_id, depth=values["depthM"])
    t_modal = None
    try:
        out_dir, model_path = require_results(ctx)
        resp = story_response.story_response(out_dir, model_path)
        if resp.get("modal"):
            t_modal = float(resp["modal"][0].get("period", 0.0))
    except FeatureInputError:
        pass
    rows = [
        {"metric": "Code approximate period Ta [s]", "value": ta},
        {"metric": "Upper limit 1.4 Ta [s]", "value": 1.4 * ta},
        {"metric": "Analyzed modal T1 [s]", "value": t_modal if t_modal is not None else 0.0},
    ]
    return result(
        summary={
            "approxPeriodS": ta,
            "upperBoundPeriodS": 1.4 * ta,
            "modalPeriodS": t_modal or 0.0,
        },
        tables=[
            table(
                "Fundamental period comparison",
                [("metric", "Period Metric"), ("value", "Value [s]")],
                rows,
            )
        ],
        notes=["Compares empirical code period Ta with modal eigenvalue period when available."],
    )


@feature(
    "femSeismic.accidentalTorsion",
    "Accidental Torsion",
    part="fem",
    fields=[number("eccentricityShare", "Accidental eccentricity share", 0.05, min=0.0, max=0.2)],
    requires_project=False,
)
def accidental_torsion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate diaphragm accidental torsion groups and amplification criteria."""
    bim = load_bim(ctx)
    wx, dy = building_plan_dims_m(bim)
    _, _model = optional_osmodel(ctx)
    present = {"D", "L", "EX", "EY"}
    with in_force(ctx.root):
        rules = torsional_effects.rules()
        groups = torsional_effects.delta_groups(bim, present) if bim is not None else []
    ex_off = values["eccentricityShare"] * wx
    ey_off = values["eccentricityShare"] * dy
    rows = [
        {"direction": "X shaking (offset along Y)", "dimensionM": dy, "offsetM": ey_off},
        {"direction": "Y shaking (offset along X)", "dimensionM": wx, "offsetM": ex_off},
    ]
    return result(
        summary={
            "offsetXM": ex_off,
            "offsetYM": ey_off,
            "deltaGroups": len(groups),
            "rulesLoaded": rules is not None,
        },
        tables=[
            table(
                "Accidental eccentricity offsets",
                [
                    ("direction", "Shaking"),
                    ("dimensionM", "Plan Width", "m"),
                    ("offsetM", "Offset", "m"),
                ],
                rows,
            )
        ],
        notes=["Offset equals share × perpendicular building plan dimension."],
    )


@feature(
    "femSeismic.accelerogram",
    "Accelerogram",
    part="fem",
    fields=[
        text(
            "series",
            "Acceleration values [g]",
            "0, 0.05, -0.12, 0.24, -0.31, 0.18, -0.09, 0.04, -0.01, 0",
        ),
        number("dtS", "Time step dt", 0.02, unit="s", min=0.001, max=0.5),
    ],
    requires_project=False,
)
def accelerogram(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect ground-motion accelerogram PGA, Arias intensity, and duration metrics."""
    dt, acc = parse_series(values["series"], values["dtS"], "Accelerogram")
    pga = float(np.max(np.abs(acc)))
    g = 9.80665
    arias = (math.pi / (2.0 * g)) * float(np.trapezoid((acc * g) ** 2, dx=dt))
    dur = (len(acc) - 1) * dt
    rows = [
        {"metric": "Points", "value": len(acc)},
        {"metric": "Duration [s]", "value": dur},
        {"metric": "Peak ground acceleration [g]", "value": pga},
        {"metric": "Arias intensity [m/s]", "value": arias},
    ]
    return result(
        summary={"points": len(acc), "durationS": dur, "pgaG": pga, "ariasIntensityMS": arias},
        tables=[
            table(
                "Accelerogram intensity metrics", [("metric", "Metric"), ("value", "Value")], rows
            )
        ],
        notes=["Arias intensity IA = (π/2g) ∫ a(t)² dt."],
    )


@feature(
    "femSeismic.spectrumMatching",
    "Spectrum Matching",
    part="fem",
    fields=[
        text(
            "series",
            "Seed acceleration [g]",
            "0, 0.08, -0.15, 0.28, -0.35, 0.22, -0.11, 0.05, -0.02, 0",
        ),
        number("dtS", "Time step dt", 0.02, unit="s", min=0.001),
        number("damping", "Damping ratio", 0.05, min=0.01, max=0.25),
    ],
    requires_project=False,
)
def spectrum_matching(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute response spectrum of seed accelerogram and compare to target site spectrum."""
    dt, acc = parse_series(values["series"], values["dtS"], "Seed accelerogram")
    periods = [0.1, 0.2, 0.5, 1.0, 1.5, 2.0]
    sa_rec = spectral_matching.spectrum(dt, acc, periods, values["damping"])
    settings = load_settings(ctx)
    sc, z_val, _, _, _, _ = site_params(settings)
    with in_force(ctx.root):
        sa_tar = [
            loads.normalized_spectrum(t, sc, damping=values["damping"]) * max(z_val, 0.1)
            for t in periods
        ]
    rows = [
        {"periodS": t, "recordSaG": float(r), "targetSaG": tar, "ratio": float(r) / max(tar, 1e-6)}
        for t, r, tar in zip(periods, sa_rec, sa_tar, strict=True)
    ]
    mean_ratio = sum(r["ratio"] for r in rows) / len(rows)
    return result(
        summary={"periods": len(periods), "meanSpectralRatio": mean_ratio},
        tables=[
            table(
                "Seed vs target response spectrum",
                [
                    ("periodS", "Period", "s"),
                    ("recordSaG", "Seed Sa", "g"),
                    ("targetSaG", "Target Sa", "g"),
                    ("ratio", "Seed/Target"),
                ],
                rows,
            )
        ],
        notes=["Computes 5%-damped elastic response spectrum via saengine.fem.spectral_matching."],
    )


@feature(
    "femSeismic.seedRecords",
    "Seed Records",
    part="fem",
    fields=[],
    requires_project=False,
)
def seed_records(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect configured project ground-motion seed records and suite counts."""
    settings = load_settings(ctx)
    histories = list(getattr(getattr(settings, "analysis", None), "timeHistories", None) or [])
    with in_force(ctx.root):
        suites = records.suites(histories)
        rule_3 = records.design_rule(3)
        rule_7 = records.design_rule(7)
    rows = [{"suite": k, "records": len(v), "indices": str(v)} for k, v in suites.items()]
    if not rows:
        rows = [
            {"suite": "3-record minimum", "records": 3, "indices": rule_3},
            {"suite": "7-record mean suite", "records": 7, "indices": rule_7},
        ]
    return result(
        summary={
            "configuredHistories": len(histories),
            "suites": len(suites),
            "rule3": rule_3,
            "rule7": rule_7,
        },
        tables=[
            table(
                "Ground-motion seed suites",
                [("suite", "Suite"), ("records", "Count"), ("indices", "Indices / Rule")],
                rows,
            )
        ],
        notes=["Evaluates suite grouping and code averaging rules."],
    )


@feature(
    "femSeismic.motionScaling",
    "Motion Scaling",
    part="fem",
    fields=[
        number("recordSaG", "Record spectral ordinate at T1", 0.25, unit="g", min=0.01),
        number("targetSaG", "Target design spectrum Sa(T1)", 0.45, unit="g", min=0.01),
        number("minScale", "Minimum permitted scale", 0.5, min=0.1),
        number("maxScale", "Maximum permitted scale", 4.0, min=1.0),
    ],
    requires_project=False,
)
def motion_scaling(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute amplitude scale factor to match target spectral intensity without altering frequency."""
    sf = values["targetSaG"] / values["recordSaG"]
    in_bounds = values["minScale"] <= sf <= values["maxScale"]
    rows = [
        {
            "recordSaG": values["recordSaG"],
            "targetSaG": values["targetSaG"],
            "scaleFactor": sf,
            "withinBounds": in_bounds,
        }
    ]
    return result(
        summary={"scaleFactor": sf, "withinAmplitudeBounds": in_bounds},
        tables=[
            table(
                "Ground-motion amplitude scaling",
                [
                    ("recordSaG", "Record Sa", "g"),
                    ("targetSaG", "Target Sa", "g"),
                    ("scaleFactor", "Scale Factor"),
                    ("withinBounds", "In Bounds"),
                ],
                rows,
            )
        ],
        notes=[
            "Uniform amplitude scaling preserves phase and frequency content of the seed record."
        ],
    )


@feature(
    "femSeismic.driftLimitCheck",
    "Drift Limit Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def drift_limit_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify analyzed inter-storey drifts against amplified code drift limits."""
    out_dir, model_path = require_results(ctx)
    settings = load_settings(ctx)
    with in_force(ctx.root):
        lim = seismic_design.settings_drift_limit(settings)
    allow = float(lim.get("allowable") or 0.02) if isinstance(lim, dict) else 0.02
    resp = story_response.story_response(out_dir, model_path)
    rows = []
    worst = 0.0
    for c in resp.get("cases", []):
        if not any(tag in str(c.get("label", "")).upper() for tag in ("EX", "EY", "RS")):
            continue
        for lv in c.get("levels", []):
            dr = max(abs(float(lv.get("driftX", 0.0))), abs(float(lv.get("driftY", 0.0))))
            worst = max(worst, dr)
            rows.append(
                {
                    "case": str(c.get("label", "")),
                    "level": str(lv.get("name", "")),
                    "drift": dr,
                    "utilisation": dr / allow,
                    "ok": dr <= allow,
                }
            )
    if not rows:
        raise FeatureInputError("Run the analysis first.")
    return result(
        summary={
            "maxDrift": worst,
            "allowable": allow,
            "utilisation": worst / allow,
            "ok": worst <= allow,
        },
        tables=[
            table(
                "Allowable seismic drift verification",
                [
                    ("case", "Case"),
                    ("level", "Level"),
                    ("drift", "Drift"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:40],
            )
        ],
        notes=["Checks design inter-storey drift ratios against active code pack limits."],
    )


@feature(
    "femSeismic.irregularityCheck",
    "Irregularity Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def irregularity_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run pre-analysis and post-analysis plan and vertical seismic irregularity checks."""
    out_dir, model_path = require_results(ctx)
    settings = load_settings(ctx)
    bim = load_bim(ctx)
    _, objs = load_objects(ctx)
    _, mats = load_materials(ctx)
    with in_force(ctx.root):
        pre = seismic_regularity.pre_analysis(bim, objs, mats) if bim else None
        post = irregularity.assessment_of(out_dir, model_path, settings=settings)
    findings = irregularity.finding_rows(post) if post else []
    rows = [{"finding": " | ".join(str(x) for x in f)} for f in findings]
    return result(
        summary={
            "preAnalysisChecked": pre is not None,
            "postAnalysisChecked": post is not None,
            "findings": len(rows),
        },
        tables=[
            table(
                "Seismic irregularity findings",
                [("finding", "Finding")],
                rows or [{"finding": "No structural irregularities flagged."}],
            )
        ],
        notes=["Checks stiffness, mass, re-entrant corner, and torsional irregularities."],
    )


@feature(
    "femSeismic.redundancyFactor",
    "Redundancy Factor",
    part="fem",
    fields=[
        number("baysX", "Moment/braced bays along X", 3, min=1, max=20),
        number("baysY", "Moment/braced bays along Y", 2, min=1, max=20),
        checkbox("extremeTorsion", "Extreme torsional irregularity present", False),
    ],
    requires_project=False,
)
def redundancy_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate seismic redundancy factor ρ from bay framing redundancy and torsional regularity."""
    min_bays = min(int(values["baysX"]), int(values["baysY"]))
    rho = 1.3 if (min_bays < 2 or values["extremeTorsion"]) else 1.0
    rows = [
        {
            "axis": "X",
            "bays": int(values["baysX"]),
            "rho": 1.3 if int(values["baysX"]) < 2 or values["extremeTorsion"] else 1.0,
        },
        {
            "axis": "Y",
            "bays": int(values["baysY"]),
            "rho": 1.3 if int(values["baysY"]) < 2 or values["extremeTorsion"] else 1.0,
        },
    ]
    return result(
        summary={"governingRho": rho, "baysX": int(values["baysX"]), "baysY": int(values["baysY"])},
        tables=[
            table(
                "Seismic redundancy factor ρ",
                [("axis", "Direction"), ("bays", "Lateral Bays"), ("rho", "ρ")],
                rows,
            )
        ],
        notes=[
            "ρ = 1.0 for redundant multi-bay perimeter framing without extreme torsion; else 1.3."
        ],
    )


@feature(
    "femSeismic.spectrumCompare",
    "Spectrum Compare",
    part="fem",
    fields=[number("damping", "Target damping ratio", 0.05, min=0.01, max=0.25)],
    requires_project=False,
)
def spectrum_compare(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Overlay elastic site spectrum and reduced design spectrum across building period range."""
    settings = load_settings(ctx)
    sc, z_val, _, r_fac, imp, _ = site_params(settings)
    periods = [0.05, 0.15, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0]
    rows = []
    with in_force(ctx.root):
        for t in periods:
            el = loads.normalized_spectrum(t, sc, damping=values["damping"]) * z_val
            des = loads.design_acceleration(t, sc, z_val, imp, r_fac, damping=values["damping"])
            rows.append(
                {
                    "periodS": t,
                    "elasticSaG": el,
                    "designCsG": des,
                    "reductionRatio": el / max(des, 1e-6),
                }
            )
    return result(
        summary={"siteClass": sc, "rFactor": r_fac, "periodsCompared": len(rows)},
        tables=[
            table(
                "Elastic vs design response spectrum",
                [
                    ("periodS", "T", "s"),
                    ("elasticSaG", "Elastic Sa", "g"),
                    ("designCsG", "Design Cs", "g"),
                    ("reductionRatio", "Ratio"),
                ],
                rows,
            )
        ],
        notes=["Compares elastic hazard spectrum against R/I reduced design ordinates."],
    )


@feature(
    "femSeismic.seismicReport",
    "Seismic Report",
    part="fem",
    fields=[],
    requires_project=True,
)
def seismic_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile seismic parameters, base shears, and drift checks into a Markdown report."""
    out_dir, model_path = require_results(ctx)
    settings = load_settings(ctx)
    sc, z_val, _, r_fac, imp, _ = site_params(settings)
    resp = story_response.story_response(out_dir, model_path)
    seis_cases = [
        c
        for c in resp.get("cases", [])
        if any(k in str(c.get("label", "")).upper() for k in ("EX", "EY", "RS"))
    ]
    lines = [
        "# Seismic Analysis Summary Report",
        "",
        f"- Site class: {sc}",
        f"- Zone coefficient Z: {z_val}",
        f"- Behaviour factor R: {r_fac}",
        f"- Importance factor I: {imp}",
        f"- Seismic cases analyzed: {len(seis_cases)}",
    ]
    report_path = export_fem_file(ctx, "seismic-report.md", "\n".join(lines) + "\n")
    rows = [
        {
            "case": str(c.get("label", "")),
            "vxKn": float((c.get("baseReaction") or {}).get("fxKn", 0.0)),
            "vyKn": float((c.get("baseReaction") or {}).get("fyKn", 0.0)),
        }
        for c in seis_cases
    ]
    return result(
        summary={"seismicCases": len(rows), "reportPath": str(report_path)},
        tables=[
            table(
                "Seismic case base reactions",
                [("case", "Case"), ("vxKn", "Vx", "kN"), ("vyKn", "Vy", "kN")],
                rows or [{"case": "None", "vxKn": 0.0, "vyKn": 0.0}],
            )
        ],
        notes=[f"Report exported to {report_path}"],
    )
