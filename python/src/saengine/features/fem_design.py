"""Design Reinforcement - Design tab: RC/steel member checks, rebar proposals, slab/punching, and foundation checks."""

from __future__ import annotations

from typing import Any

from saengine.design import (
    check as design_check,
)
from saengine.design import (
    development_factors,
    proposal,
    slender,
)
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    table,
)
from saengine.features.fem_common import (
    concrete_rebar_defaults,
    load_bim,
    load_materials,
    load_objects,
    load_settings,
    optional_osmodel,
    require_results,
)
from saengine.report.clauses import in_force


def _run_design_checks(ctx: FeatureContext) -> dict[str, Any]:
    """Run full saengine.design.check.design on 08 FEM/model.results."""
    out_dir, _ = require_results(ctx)
    _, model = optional_osmodel(ctx)
    bim = load_bim(ctx)
    obj_lib, _ = load_objects(ctx)
    mat_lib, _ = load_materials(ctx)
    settings = load_settings(ctx)
    if not (model and bim and obj_lib and mat_lib):
        raise FeatureInputError("Missing BIM, Objects, Materials, or OSModel to run design checks.")
    with in_force(ctx.root):
        return design_check.design(model, out_dir, bim, obj_lib, mat_lib, settings)


def _filter_member_checks(
    res: dict[str, Any], kind: str, keyword: str = ""
) -> list[dict[str, Any]]:
    rows = []
    kw = keyword.lower()
    for m in res.get("members", []):
        if kind and str(m.get("kind", "")).lower() != kind:
            continue
        for c in m.get("checks", []):
            if kw and kw not in str(c.get("name", "")).lower():
                continue
            rows.append(
                {
                    "member": str(m.get("member", "")),
                    "check": str(c.get("name", "")),
                    "demand": float(c.get("demand", 0.0) or 0.0),
                    "capacity": float(c.get("capacity", 0.0) or 0.0),
                    "utilisation": float(c.get("utilisation", 0.0) or 0.0),
                    "ok": bool(c.get("ok", True)),
                }
            )
    return rows


@feature(
    "design.rebarDesign",
    "Rebar Design",
    part="fem",
    fields=[],
    requires_project=True,
)
def rebar_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design longitudinal reinforcement proposals for all RC object types from 08 FEM/model.results."""
    out_dir, model_path = require_results(ctx)
    with in_force(ctx.root):
        prop = proposal.design_proposal(out_dir, model_path)
    entries = prop.get("entries", []) if isinstance(prop, dict) else []
    rows = [
        {
            "type": str(e.get("id", "")),
            "kind": str(e.get("kind", "")),
            "utilisation": float(e.get("utilisation", 0.0) or 0.0),
            "status": str(e.get("status", "proposed")),
        }
        for e in entries[:40]
    ]
    return result(
        summary={"typesDesigned": len(entries)},
        tables=[
            table(
                "Longitudinal reinforcement design proposals",
                [
                    ("type", "Object Type"),
                    ("kind", "Kind"),
                    ("utilisation", "DCR"),
                    ("status", "Status"),
                ],
                rows or [{"type": "None", "kind": "-", "utilisation": 0.0, "status": "-"}],
            )
        ],
        notes=[
            "Lightest passing reinforcement proposed per object type via saengine.design.proposal."
        ],
    )


@feature(
    "design.shearDesign",
    "Shear Design",
    part="fem",
    fields=[],
    requires_project=True,
)
def shear_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check and design transverse shear reinforcement across all analyzed members."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "", "shear")
    return result(
        summary={"shearChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Member shear design checks",
                [
                    ("member", "Member"),
                    ("check", "Check"),
                    ("demand", "Vu"),
                    ("capacity", "φVn"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "Shear",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Checks concrete Vc + stirrup Vs capacity at all member stations."],
    )


@feature(
    "design.torsionDesign",
    "Torsion Design",
    part="fem",
    fields=[],
    requires_project=True,
)
def torsion_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check beam threshold torsion and closed-stirrup / longitudinal torsion steel requirements."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "", "torsion")
    return result(
        summary={"torsionChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Torsion design checks",
                [
                    ("member", "Member"),
                    ("check", "Check"),
                    ("demand", "Tu"),
                    ("capacity", "Limit"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "Torsion below threshold",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Evaluated via saengine.design.torsion."],
    )


@feature(
    "design.barSelection",
    "Bar Selection",
    part="fem",
    fields=[],
    requires_project=True,
)
def bar_selection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select practical reinforcing bar diameters and counts satisfying member design checks."""
    out_dir, model_path = require_results(ctx)
    with in_force(ctx.root):
        prop = proposal.propose(out_dir, model_path)
    entries = prop.get("entries", []) if isinstance(prop, dict) else []
    rows = [
        {"type": str(e.get("id", "")), "summary": str(e.get("summary", e.get("status", "")))}
        for e in entries[:40]
    ]
    return result(
        summary={"typesProcessed": len(entries)},
        tables=[
            table(
                "Selected bar arrangements",
                [("type", "Type"), ("summary", "Selected Bars")],
                rows or [{"type": "None", "summary": "-"}],
            )
        ],
        notes=["Arranges bars within clear spacing and symmetric layout rules."],
    )


@feature(
    "design.anchorageCheck",
    "Anchorage Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def anchorage_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify bar anchorage and cutoff checks across analyzed structural members."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "", "anchor")
    return result(
        summary={"anchorageChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Member anchorage verification",
                [
                    ("member", "Member"),
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:40]
                or [
                    {
                        "member": "All",
                        "check": "Anchorage",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Verifies straight and hooked anchorage development at supports."],
    )


@feature(
    "design.developmentLength",
    "Development Length",
    part="fem",
    fields=[
        number("barDiameterMm", "Bar diameter db", 20.0, unit="mm", min=6.0, max=50.0),
        checkbox("topBar", "Top bar (>300 mm concrete below)", False),
        number("clearCoverMm", "Clear cover / confinement cd", 40.0, unit="mm", min=15.0),
    ],
    requires_project=False,
)
def development_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute tension, compression, and standard 90-degree hook development lengths."""
    fc, fy = concrete_rebar_defaults(ctx)
    db = values["barDiameterMm"]
    with in_force(ctx.root):
        ten = development_factors.tension_length(
            db, fy, fc, top=values["topBar"], cd=values["clearCoverMm"]
        )
        comp = development_factors.compression_length(db, fy, fc)
        hook = development_factors.hook_length(
            db, fy, fc, top=values["topBar"], cd=values["clearCoverMm"]
        )
    rows = [
        {"kind": "Straight tension ld", "lengthMm": float(ten.get("length", 0.0))},
        {"kind": "Compression ldc", "lengthMm": float(comp.get("length", 0.0))},
        {"kind": "Standard 90° hook ldh", "lengthMm": float(hook.get("length", 0.0))},
    ]
    return result(
        summary={
            "tensionLengthMm": rows[0]["lengthMm"],
            "compressionLengthMm": rows[1]["lengthMm"],
            "hookLengthMm": rows[2]["lengthMm"],
        },
        tables=[
            table(
                f"Development lengths (Ø{db:g}, fc={fc:g}, fy={fy:g})",
                [("kind", "Anchorage Type"), ("lengthMm", "Length", "mm")],
                rows,
            )
        ],
        notes=["Computed via saengine.design.development_factors under active code pack."],
    )


@feature(
    "design.beamFlexureCheck",
    "Beam Flexure Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def beam_flexure_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check beam sagging and hogging flexural capacities against envelope moments."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "beam", "flexure") or _filter_member_checks(
        res, "beam", "moment"
    )
    return result(
        summary={"beamFlexureChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Beam flexure checks",
                [
                    ("member", "Beam"),
                    ("check", "Check"),
                    ("demand", "Mu"),
                    ("capacity", "φMn"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "Beam flexure",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Evaluated for sagging and hogging moments including minimum/maximum steel bounds."],
    )


@feature(
    "design.beamShearCheck",
    "Beam Shear Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def beam_shear_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check beam shear strength and stirrup limits across all beam stations."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "beam", "shear")
    return result(
        summary={"beamShearChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Beam shear checks",
                [
                    ("member", "Beam"),
                    ("check", "Check"),
                    ("demand", "Vu"),
                    ("capacity", "φVn"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "Beam shear",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Includes concrete Vc, stirrup Vs, and upper strut-crushing shear caps."],
    )


@feature(
    "design.beamTorsionCheck",
    "Beam Torsion Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def beam_torsion_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check combined shear and torsion interaction in beams."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "beam", "torsion")
    return result(
        summary={"beamTorsionChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Beam combined shear & torsion checks",
                [
                    ("member", "Beam"),
                    ("check", "Check"),
                    ("demand", "Tu"),
                    ("capacity", "Limit"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "Beam torsion",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Checks combined shear + torsion web crushing and closed stirrup demand."],
    )


@feature(
    "design.deflectionLimit",
    "Deflection Limit",
    part="fem",
    fields=[],
    requires_project=True,
)
def deflection_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify beam deflection checks from analyzed member demands."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "beam", "deflect") + _filter_member_checks(
        res, "beam", "span"
    )
    return result(
        summary={"deflectionChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Beam deflection limit checks",
                [
                    ("member", "Beam"),
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Limit"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "Span/depth",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Checks immediate and long-term deflections against span-based code limits."],
    )


@feature(
    "design.columnAxialCheck",
    "Column Axial Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def column_axial_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check column axial compression/tension capacity against design combinations."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "column", "axial")
    return result(
        summary={"columnAxialChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Column axial capacity checks",
                [
                    ("member", "Column"),
                    ("check", "Check"),
                    ("demand", "Pu"),
                    ("capacity", "φPn"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "Axial",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Includes 0.80/0.85 φP0 maximum axial cap for tied/spiral columns."],
    )


@feature(
    "design.biaxialBending",
    "Biaxial Bending",
    part="fem",
    fields=[],
    requires_project=True,
)
def biaxial_bending(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check columns under combined axial force and biaxial bending (P-M2-M3 interaction)."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "column", "interaction") or _filter_member_checks(
        res, "column", "flexure"
    )
    return result(
        summary={"biaxialChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Column biaxial P-M2-M3 checks",
                [
                    ("member", "Column"),
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "P-M-M",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Evaluated on 3D strain-compatibility interaction surfaces."],
    )


@feature(
    "design.slendernessCheck",
    "Slenderness Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def slenderness_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assess column slenderness k·lu/r and second-order moment magnification checks."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "column", "slender")
    return result(
        summary={"slendernessChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Column slenderness checks",
                [
                    ("member", "Column"),
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Limit"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "Slenderness",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Evaluates k·lu/r threshold and nonsway/sway moment magnifiers."],
    )


@feature(
    "design.bucklingLength",
    "Buckling Length",
    part="fem",
    fields=[
        number("psiA", "Joint stiffness ratio ΨA", 1.2, min=0.0, max=50.0),
        number("psiB", "Joint stiffness ratio ΨB", 1.5, min=0.0, max=50.0),
        number("clearLengthMm", "Unsupported length lu", 3000.0, unit="mm", min=500.0),
        checkbox("swayFrame", "Unbraced sway frame", True),
    ],
    requires_project=False,
)
def buckling_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute column effective buckling length factor K and effective length K·lu."""
    k = (
        slender.k_sway(values["psiA"], values["psiB"])
        if values["swayFrame"]
        else slender.k_nonsway(values["psiA"], values["psiB"])
    )
    klu = k * values["clearLengthMm"]
    rows = [
        {
            "frameType": "Sway" if values["swayFrame"] else "Braced",
            "psiA": values["psiA"],
            "psiB": values["psiB"],
            "kFactor": k,
            "effectiveLengthMm": klu,
        }
    ]
    return result(
        summary={"kFactor": k, "effectiveLengthMm": klu},
        tables=[
            table(
                "Column effective buckling length",
                [
                    ("frameType", "Frame"),
                    ("psiA", "ΨA"),
                    ("psiB", "ΨB"),
                    ("kFactor", "K"),
                    ("effectiveLengthMm", "K·lu", "mm"),
                ],
                rows,
            )
        ],
        notes=["Evaluated via saengine.design.slender alignment-chart equations."],
    )


@feature(
    "design.slabFlexureCheck",
    "Slab Flexure Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def slab_flexure_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check slab reinforcement capacity against Wood-Armer design moments."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "slab", "")
    return result(
        summary={"slabChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Slab flexural & shear design checks",
                [
                    ("member", "Slab"),
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "Slab",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Evaluated from shell bending moments and slab mesh layout."],
    )


@feature(
    "design.punchingCheck",
    "Punching Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def punching_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check slab-column punching shear perimeter and shear stud requirements."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "slab", "punch")
    return result(
        summary={"punchingChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Slab-column punching shear checks",
                [
                    ("member", "Location"),
                    ("check", "Check"),
                    ("demand", "vu"),
                    ("capacity", "φvc"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "Punching",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=[
            "Checks critical perimeter b0 at d/2 from column faces including unbalanced moment transfer."
        ],
    )


@feature(
    "design.crackControlCheck",
    "Crack Control Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def crack_control_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify bar spacing and service steel stress for crack control in slabs and beams."""
    res = _run_design_checks(ctx)
    rows = _filter_member_checks(res, "", "crack") + _filter_member_checks(res, "", "spacing")
    return result(
        summary={"crackControlChecks": len(rows), "failing": sum(1 for r in rows if not r["ok"])},
        tables=[
            table(
                "Crack control & spacing checks",
                [
                    ("member", "Member"),
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Limit"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows[:50]
                or [
                    {
                        "member": "-",
                        "check": "Crack control",
                        "demand": 0.0,
                        "capacity": 0.0,
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=["Checks bar spacing and tension-face crack widths."],
    )


@feature(
    "design.footingDesign",
    "Footing Design",
    part="fem",
    fields=[],
    requires_project=True,
)
def footing_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size and check footings from 08 FEM/model.results support reactions."""
    require_results(ctx)
    from saengine.substructure import context as sub_ctx_mod
    from saengine.substructure import shallow

    root = ctx.root
    if root is None:
        raise FeatureInputError("Open a project folder first.")
    sc = sub_ctx_mod.load_context(root)
    if sc.loads is None:
        raise FeatureInputError("Run the analysis first.")
    with in_force(ctx.root):
        res_f = shallow.design_footings(sc)
    rows = [
        {
            "footing": str(f.get("id", "")),
            "size": str(f.get("size", "")),
            "utilisation": float(f.get("utilisation", 0.0) or 0.0),
            "ok": bool(f.get("ok", True)),
        }
        for f in (res_f if isinstance(res_f, list) else [])
    ]
    return result(
        summary={"footingsChecked": len(rows)},
        tables=[
            table(
                "Footing design from FEM reactions",
                [("footing", "Footing"), ("size", "Size"), ("utilisation", "DCR"), ("ok", "OK")],
                rows
                or [
                    {
                        "footing": "No footings in 09 Substructure",
                        "size": "-",
                        "utilisation": 0.0,
                        "ok": True,
                    }
                ],
            )
        ],
        notes=[
            "Reads support reactions from 08 FEM/model.results into saengine.substructure.shallow."
        ],
    )


@feature(
    "design.pileCapCheck",
    "Pile Cap Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def pile_cap_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check pile cap shear, bending, and strut action from 08 FEM/model.results reactions."""
    require_results(ctx)
    from saengine.substructure import context as sub_ctx_mod
    from saengine.substructure import pilecap

    if ctx.root is None:
        raise FeatureInputError("Open a project folder first.")
    sc = sub_ctx_mod.load_context(ctx.root)
    if sc.loads is None:
        raise FeatureInputError("Run the analysis first.")
    with in_force(ctx.root):
        caps = pilecap.design_pile_caps(sc)
    rows = [
        {
            "cap": str(c.get("id", "")),
            "utilisation": float(c.get("utilisation", 0.0) or 0.0),
            "ok": bool(c.get("ok", True)),
        }
        for c in (caps if isinstance(caps, list) else [])
    ]
    return result(
        summary={"pileCapsChecked": len(rows)},
        tables=[
            table(
                "Pile cap structural checks",
                [("cap", "Pile Cap"), ("utilisation", "DCR"), ("ok", "OK")],
                rows
                or [{"cap": "No pile caps in 09 Substructure", "utilisation": 0.0, "ok": True}],
            )
        ],
        notes=["Evaluated via saengine.substructure.pilecap."],
    )


@feature(
    "design.basePressureCheck",
    "Base Pressure Check",
    part="fem",
    fields=[
        number("allowableBearingKpa", "Allowable soil bearing qa", 150.0, unit="kPa", min=10.0)
    ],
    requires_project=True,
)
def base_pressure_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check soil bearing pressures under column base reactions from 08 FEM/model.results."""
    require_results(ctx)
    from saengine.substructure import context as sub_ctx_mod

    if ctx.root is None:
        raise FeatureInputError("Open a project folder first.")
    sc = sub_ctx_mod.load_context(ctx.root)
    if sc.loads is None:
        raise FeatureInputError("Run the analysis first.")
    rows = []
    for bid, base in list(sc.loads.bases.items())[:30]:
        area = max(float(getattr(base, "area", 4.0) or 4.0), 0.25)
        fz = 0.0
        for case_map in sc.loads.cases.values():
            fz = max(
                fz,
                sum(abs(float(case_map.get(nid, [0, 0, 0])[2])) for nid, _ in base.nodes) / 1000.0,
            )
        q_kpa = fz / area
        rows.append(
            {
                "base": str(bid),
                "reactionKn": fz,
                "pressureKpa": q_kpa,
                "ok": q_kpa <= values["allowableBearingKpa"],
            }
        )
    return result(
        summary={"basesChecked": len(rows), "allowableKpa": values["allowableBearingKpa"]},
        tables=[
            table(
                "Base bearing pressure check",
                [
                    ("base", "Support"),
                    ("reactionKn", "Fz", "kN"),
                    ("pressureKpa", "q", "kPa"),
                    ("ok", "OK"),
                ],
                rows or [{"base": "None", "reactionKn": 0.0, "pressureKpa": 0.0, "ok": True}],
            )
        ],
        notes=["Compares peak vertical base reaction divided by footing footprint against qa."],
    )
