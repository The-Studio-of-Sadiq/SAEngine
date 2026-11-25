"""Objects - Library Checks tab: stiffness modifiers, consistency, geometry, rebar fit & library audits."""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design.bars import column_min_clear, diameters
from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.objects_common import (
    materials_or_default,
    objects_or_default,
    require_objects,
    require_root,
    safe_json,
    save_export,
    used_type_ids,
)
from saengine.library import objects as o
from saengine.library.check import check_library
from saengine.library.modifiers import FrameModifiers, ShellModifiers, resolve_modifiers
from saengine.library.sections import section_properties
from saengine.report.clauses import in_force


@feature(
    "libraryChecks.wallModifiers",
    "Wall Modifiers",
    part="objects",
    fields=[
        select(
            "state",
            "Wall design state",
            [
                ("uncracked", "Uncracked (service / wind)"),
                ("cracked", "Cracked (ultimate seismic)"),
            ],
            "cracked",
        ),
        number("membrane", "Membrane stiffness factor f11/f22", 0.35, min=0.05, max=2.0),
        number("bending", "Out-of-plane bending factor m11/m22", 0.35, min=0.05, max=2.0),
        number("mass", "Mass multiplier", 1.0, min=0.0, max=2.0),
        number("weight", "Weight multiplier", 1.0, min=0.0, max=2.0),
    ],
    requires_project=False,
)
def wall_modifiers(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate shell stiffness modifiers for wall elements and compare with code-pack defaults."""
    mod = ShellModifiers(
        membrane=values["membrane"],
        bending=values["bending"],
        mass=values["mass"],
        weight=values["weight"],
    )
    with in_force(ctx.root):
        pack_cracked = code_context.pack_table("concrete").crackedStiffness
        wall_def = float(getattr(pack_cracked, "wallCracked", 0.35))
        wall_uncr = float(getattr(pack_cracked, "wallUncracked", 0.70))
    target = wall_uncr if values["state"] == "uncracked" else wall_def
    rows = [
        {"factor": "Membrane f11, f22, f12", "entered": mod.membrane, "packDefault": target},
        {"factor": "Bending m11, m22, m12", "entered": mod.bending, "packDefault": target},
        {"factor": "Mass", "entered": mod.mass, "packDefault": 1.0},
        {"factor": "Weight", "entered": mod.weight, "packDefault": 1.0},
    ]
    return result(
        summary={
            "state": values["state"],
            "membrane": mod.membrane,
            "bending": mod.bending,
            "packWallDefault": target,
        },
        tables=[
            table(
                "Wall shell stiffness modifiers",
                [
                    ("factor", "Modifier"),
                    ("entered", "Entered"),
                    ("packDefault", "Code-pack default"),
                ],
                rows,
            )
        ],
        notes=[
            "Code-pack cracked/uncracked wall stiffness defaults are read from the active code pack."
        ],
    )


@feature(
    "libraryChecks.slabModifiers",
    "Slab Modifiers",
    part="objects",
    fields=[
        number("membrane", "In-plane membrane modifier", 1.0, min=0.05, max=2.0),
        number("bending", "Flexural bending modifier", 0.25, min=0.05, max=2.0),
        number("mass", "Mass multiplier", 1.0, min=0.0, max=2.0),
        number("weight", "Weight multiplier", 1.0, min=0.0, max=2.0),
    ],
    requires_project=False,
)
def slab_modifiers(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate membrane and flexural bending modifiers for floor slabs."""
    mod = ShellModifiers(
        membrane=values["membrane"],
        bending=values["bending"],
        mass=values["mass"],
        weight=values["weight"],
    )
    with in_force(ctx.root):
        slab_def = float(
            getattr(code_context.pack_table("concrete").crackedStiffness, "slab", 0.25)
        )
    rows = [
        {"factor": "Membrane (diaphragm action)", "entered": mod.membrane, "packDefault": 1.0},
        {"factor": "Bending (out-of-plane)", "entered": mod.bending, "packDefault": slab_def},
        {"factor": "Mass", "entered": mod.mass, "packDefault": 1.0},
        {"factor": "Weight", "entered": mod.weight, "packDefault": 1.0},
    ]
    return result(
        summary={"membrane": mod.membrane, "bending": mod.bending, "packSlabDefault": slab_def},
        tables=[
            table(
                "Slab shell modifiers",
                [
                    ("factor", "Modifier"),
                    ("entered", "Entered"),
                    ("packDefault", "Code-pack default"),
                ],
                rows,
            )
        ],
        notes=[
            "Flat and two-way slabs use reduced out-of-plane bending modifiers for cracked drift analysis."
        ],
    )


@feature(
    "libraryChecks.columnModifiers",
    "Column Modifiers",
    part="objects",
    fields=[
        number("area", "Axial area modifier A", 1.0, min=0.1, max=2.0),
        number("i33", "Major inertia modifier I33", 0.70, min=0.1, max=2.0),
        number("i22", "Minor inertia modifier I22", 0.70, min=0.1, max=2.0),
        number("j", "Torsional constant modifier J", 1.0, min=0.05, max=2.0),
    ],
    requires_project=False,
)
def column_modifiers(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate axial, flexural, and torsional stiffness modifiers for frame columns and beams."""
    mod = FrameModifiers(A=values["area"], I33=values["i33"], I22=values["i22"], J=values["j"])
    with in_force(ctx.root):
        col_def = float(
            getattr(code_context.pack_table("concrete").crackedStiffness, "column", 0.70)
        )
        beam_def = float(
            getattr(code_context.pack_table("concrete").crackedStiffness, "beam", 0.35)
        )
    rows = [
        {"factor": "Axial area A", "entered": mod.A, "colDefault": 1.0, "beamDefault": 1.0},
        {
            "factor": "Major bending I33",
            "entered": mod.I33,
            "colDefault": col_def,
            "beamDefault": beam_def,
        },
        {
            "factor": "Minor bending I22",
            "entered": mod.I22,
            "colDefault": col_def,
            "beamDefault": beam_def,
        },
        {"factor": "Torsion J", "entered": mod.J, "colDefault": 1.0, "beamDefault": 1.0},
    ]
    return result(
        summary={
            "areaFactor": mod.A,
            "i33Factor": mod.I33,
            "i22Factor": mod.I22,
            "packColumnDefault": col_def,
        },
        tables=[
            table(
                "Frame stiffness modifiers",
                [
                    ("factor", "Property"),
                    ("entered", "Entered"),
                    ("colDefault", "Column default"),
                    ("beamDefault", "Beam default"),
                ],
                rows,
            )
        ],
        notes=[
            "Compares entered frame modifiers with active code-pack cracked stiffness defaults."
        ],
    )


@feature(
    "libraryChecks.modifierSets",
    "Modifier Sets",
    part="objects",
    fields=[],
    requires_project=False,
)
def modifier_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List resolved stiffness modifiers for every object type in 04 Objects (or default library)."""
    lib, is_proj = objects_or_default(ctx)
    rows = []
    for obj in lib.objects:
        resolved = resolve_modifiers(None, obj)
        summary_str = (
            ", ".join(f"{k}={v[0]:g}" for k, v in resolved.items()) or "code-pack defaults"
        )
        rows.append(
            {"id": obj.id, "kind": obj.kind, "customCount": len(resolved), "modifiers": summary_str}
        )
    return result(
        summary={
            "source": "project" if is_proj else "default library",
            "typesChecked": len(rows),
            "overriddenTypes": sum(1 for r in rows if r["customCount"] > 0),
        },
        tables=[
            table(
                "Object type modifier sets",
                [
                    ("id", "Object ID"),
                    ("kind", "Kind"),
                    ("customCount", "Overrides"),
                    ("modifiers", "Resolved modifiers"),
                ],
                rows,
            )
        ],
        notes=["Unset modifiers automatically inherit the code pack's cracked stiffness factor."],
    )


@feature(
    "libraryChecks.sectionChecks",
    "Section Checks",
    part="objects",
    fields=[],
    requires_project=False,
)
def section_checks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate all object library definitions against schema, material links, and guardrails."""
    lib, is_proj = objects_or_default(ctx)
    mats, _ = materials_or_default(ctx)
    with in_force(ctx.root):
        problems = check_library(
            "objects",
            lib.model_dump_json(by_alias=True),
            mats.model_dump_json(by_alias=True),
        )
    rows = [
        {
            "index": str(p.get("index")),
            "path": str(p.get("path")),
            "severity": str(p.get("severity", "error")),
            "message": str(p.get("message")),
        }
        for p in problems
    ]
    return result(
        summary={
            "source": "project" if is_proj else "default library",
            "issueCount": len(rows),
            "allClean": len(rows) == 0,
        },
        tables=[
            table(
                "Section & object guardrail checks",
                [
                    ("index", "Idx"),
                    ("path", "Field"),
                    ("severity", "Severity"),
                    ("message", "Message"),
                ],
                rows
                or [{"index": "-", "path": "-", "severity": "ok", "message": "No section issues"}],
            )
        ],
        notes=["Runs engine check_library (schema, material cross-checks, and U2 guardrails)."],
    )


@feature(
    "libraryChecks.rebarChecks",
    "Rebar Checks",
    part="objects",
    fields=[],
    requires_project=False,
)
def rebar_checks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check bar spacing, cover, and allowed diameters for every reinforced object type."""
    lib, _ = objects_or_default(ctx)
    with in_force(ctx.root):
        allowed_dias = set(diameters("all"))
    rows = []
    fails = 0
    for obj in lib.objects:
        reinf = getattr(obj, "reinforcement", None)
        if reinf is None:
            continue
        prof = getattr(obj, "profile", None)
        issues = []
        long_bars = getattr(reinf, "longitudinal", None) or []
        for grp in long_bars:
            if grp.dia not in allowed_dias:
                issues.append(f"dia {grp.dia:g} mm not in code-pack bar set")
            if isinstance(prof, o.RectangleProfile) and grp.position in ("top", "bottom"):
                clear = (prof.xDim - 2 * reinf.cover - 20.0 - grp.count * grp.dia) / max(
                    1, grp.count - 1
                )
                req = max(25.0, grp.dia)
                if clear < req:
                    issues.append(f"{grp.position} clear spacing {clear:.1f} < {req:.1f} mm")
        if issues:
            fails += 1
        rows.append(
            {
                "id": obj.id,
                "kind": obj.kind,
                "coverMm": reinf.cover,
                "ok": len(issues) == 0,
                "notes": "; ".join(issues) or "OK",
            }
        )
    return result(
        summary={"checkedTypes": len(rows), "failingTypes": fails, "allPass": fails == 0},
        tables=[
            table(
                "Reinforcement detailing check",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("coverMm", "Cover", "mm"),
                    ("ok", "Pass"),
                    ("notes", "Findings"),
                ],
                rows,
            )
        ],
        notes=["Checks bar diameters against code-pack bar set and horizontal clear spacing."],
    )


@feature(
    "libraryChecks.unitChecks",
    "Unit Checks",
    part="objects",
    fields=[],
    requires_project=False,
)
def unit_checks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit section dimensions and thicknesses for plausible SI millimetre magnitudes."""
    lib, _ = objects_or_default(ctx)
    rows = []
    flagged = 0
    for obj in lib.objects:
        prof = getattr(obj, "profile", None)
        flag = False
        detail = "SI mm range OK"
        if isinstance(prof, o.RectangleProfile):
            if min(prof.xDim, prof.yDim) < 50.0 or max(prof.xDim, prof.yDim) > 5000.0:
                flag = True
                detail = f"Unusual dimension ({prof.xDim:g}x{prof.yDim:g} mm) — possible m/cm entry"
        elif getattr(obj, "thickness", None) is not None:
            t = float(obj.thickness)
            if t < 40.0 or t > 3000.0:
                flag = True
                detail = f"Unusual thickness ({t:g} mm) — possible m/cm entry"
        if flag:
            flagged += 1
        rows.append({"id": obj.id, "kind": obj.kind, "ok": not flag, "detail": detail})
    return result(
        summary={"checkedTypes": len(rows), "unitFlags": flagged, "allConsistent": flagged == 0},
        tables=[
            table(
                "SI unit magnitude audit",
                [("id", "ID"), ("kind", "Kind"), ("ok", "OK"), ("detail", "Check")],
                rows,
            )
        ],
        notes=[
            "Detects dimensions that appear to have been entered in metres or centimetres instead of mm."
        ],
    )


@feature(
    "libraryChecks.sectionPropertyCheck",
    "Section Property Check",
    part="objects",
    fields=[],
    requires_project=False,
)
def section_property_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recompute section properties via FEM and verify against analytical closed-form values."""
    lib, _ = objects_or_default(ctx)
    rows = []
    max_err = 0.0
    for obj in lib.objects:
        prof = getattr(obj, "profile", None)
        if prof is None or (isinstance(prof, o.DesignedProfile) and ctx.root is None):
            continue
        with in_force(ctx.root):
            props = section_properties(prof)
        if isinstance(prof, o.RectangleProfile):
            ana_a = prof.xDim * prof.yDim
            ana_ixx = prof.xDim * prof.yDim**3 / 12.0
        elif isinstance(prof, o.CircleProfile):
            ana_a = math.pi * prof.radius**2
            ana_ixx = math.pi * prof.radius**4 / 4.0
        else:
            ana_a = props.area
            ana_ixx = props.ixx
        err_pct = abs(props.ixx - ana_ixx) / ana_ixx * 100.0 if ana_ixx > 0 else 0.0
        max_err = max(max_err, err_pct)
        rows.append(
            {
                "id": obj.id,
                "femAreaMm2": props.area,
                "analyticalAreaMm2": ana_a,
                "ixxDiffPercent": err_pct,
            }
        )
    return result(
        summary={
            "checkedProfiles": len(rows),
            "maxIxxDiffPercent": max_err,
            "allMatch": max_err < 1.0,
        },
        tables=[
            table(
                "FEM vs analytical property check",
                [
                    ("id", "ID"),
                    ("femAreaMm2", "FEM A", "mm2"),
                    ("analyticalAreaMm2", "Analytic A", "mm2"),
                    ("ixxDiffPercent", "Ixx diff", "%"),
                ],
                rows,
            )
        ],
        notes=["Compares finite-element mesh integration against closed-form geometry."],
    )


@feature(
    "libraryChecks.duplicateSection",
    "Duplicate Section",
    part="objects",
    fields=[],
    requires_project=False,
)
def duplicate_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Find object types sharing identical element kind, material, and profile dimensions."""
    lib, _ = objects_or_default(ctx)
    seen: dict[str, list[str]] = {}
    for obj in lib.objects:
        prof = getattr(obj, "profile", None)
        sig = f"{obj.kind}|{obj.material}|{prof.model_dump(mode='json') if prof else getattr(obj, 'thickness', '')}"
        seen.setdefault(sig, []).append(obj.id)
    rows = [
        {"signature": k, "ids": ", ".join(v), "count": len(v)}
        for k, v in seen.items()
        if len(v) > 1
    ]
    return result(
        summary={"totalTypes": len(lib.objects), "duplicateGroups": len(rows)},
        tables=[
            table(
                "Duplicate section signatures",
                [("ids", "Duplicate IDs"), ("count", "Count"), ("signature", "Profile signature")],
                rows or [{"ids": "None", "count": 0, "signature": "All object types are unique"}],
            )
        ],
        notes=["Groups object types whose kind, material, and profile geometry are identical."],
    )


@feature(
    "libraryChecks.extremeFibreCheck",
    "Extreme Fibre Check",
    part="objects",
    fields=[],
    requires_project=False,
)
def extreme_fibre_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute extreme fibre distances c_top, c_bot, c_left, c_right from section centroids."""
    lib, _ = objects_or_default(ctx)
    rows = []
    for obj in lib.objects:
        prof = getattr(obj, "profile", None)
        if prof is None or (isinstance(prof, o.DesignedProfile) and ctx.root is None):
            continue
        with in_force(ctx.root):
            props = section_properties(prof)
        if isinstance(prof, o.RectangleProfile):
            ct = cb = prof.yDim / 2.0
        elif isinstance(prof, o.CircleProfile):
            ct = cb = prof.radius
        elif isinstance(prof, o.RectangleHollowProfile):
            ct = cb = prof.yDim / 2.0
        else:
            ct = props.cy
            cb = props.cy
        rows.append(
            {"id": obj.id, "cTopMm": ct, "cBotMm": cb, "sxTopMm3": props.ixx / ct if ct else 0.0}
        )
    return result(
        summary={"checkedProfiles": len(rows)},
        tables=[
            table(
                "Extreme fibre distances & elastic moduli",
                [
                    ("id", "ID"),
                    ("cTopMm", "c_top", "mm"),
                    ("cBotMm", "c_bot", "mm"),
                    ("sxTopMm3", "Sx", "mm3"),
                ],
                rows,
            )
        ],
        notes=["Elastic section modulus Sx = Ixx / c_extreme."],
    )


@feature(
    "libraryChecks.torsionConstantCheck",
    "Torsion Constant Check",
    part="objects",
    fields=[],
    requires_project=False,
)
def torsion_constant_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Screen torsional constants J against Saint-Venant / Bredt bounds for each profile family."""
    lib, _ = objects_or_default(ctx)
    rows = []
    for obj in lib.objects:
        prof = getattr(obj, "profile", None)
        if prof is None or (isinstance(prof, o.DesignedProfile) and ctx.root is None):
            continue
        with in_force(ctx.root):
            props = section_properties(prof)
        j_polar = props.ixx + props.iyy
        ratio = props.j / j_polar if j_polar > 0 else 0.0
        rows.append(
            {
                "id": obj.id,
                "shape": prof.shape,
                "jMm4": props.j,
                "jOverIp": ratio,
                "ok": 0.0 < props.j <= j_polar * 1.05,
            }
        )
    return result(
        summary={"checkedProfiles": len(rows), "allWithinPolarBound": all(r["ok"] for r in rows)},
        tables=[
            table(
                "Torsional constant J screening",
                [
                    ("id", "ID"),
                    ("shape", "Shape"),
                    ("jMm4", "J", "mm4"),
                    ("jOverIp", "J / (Ixx+Iyy)"),
                    ("ok", "Valid"),
                ],
                rows,
            )
        ],
        notes=[
            "By Saint-Venant warping theory, J <= polar moment (Ixx + Iyy) with equality only for circles."
        ],
    )


@feature(
    "libraryChecks.barFitCheck",
    "Bar Fit Check",
    part="objects",
    fields=[number("aggregateMm", "Max coarse aggregate size", 20.0, unit="mm", min=5.0)],
    requires_project=False,
)
def bar_fit_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Confirm that specified longitudinal bars physically fit within section width and cover."""
    lib, _ = objects_or_default(ctx)
    rows = []
    fails = 0
    for obj in lib.objects:
        prof = getattr(obj, "profile", None)
        reinf = getattr(obj, "reinforcement", None)
        if not isinstance(prof, o.RectangleProfile) or reinf is None:
            continue
        for grp in getattr(reinf, "longitudinal", ()):
            if grp.position not in ("top", "bottom"):
                continue
            avail = prof.xDim - 2.0 * reinf.cover - 20.0
            clear = (avail - grp.count * grp.dia) / max(1, grp.count - 1)
            with in_force(ctx.root):
                req = (
                    column_min_clear(grp.dia, values["aggregateMm"])
                    if obj.kind == "column"
                    else max(25.0, grp.dia, 4.0 / 3.0 * values["aggregateMm"])
                )
            ok = clear >= req
            if not ok:
                fails += 1
            rows.append(
                {
                    "id": obj.id,
                    "face": grp.position,
                    "bars": f"{grp.count}T{grp.dia:g}",
                    "clearMm": clear,
                    "reqMm": req,
                    "ok": ok,
                }
            )
    return result(
        summary={"checkedFaces": len(rows), "fitFailures": fails, "allFit": fails == 0},
        tables=[
            table(
                "Longitudinal bar fit audit",
                [
                    ("id", "ID"),
                    ("face", "Face"),
                    ("bars", "Bars"),
                    ("clearMm", "Clear", "mm"),
                    ("reqMm", "Min req", "mm"),
                    ("ok", "Fits"),
                ],
                rows,
            )
        ],
        notes=["Checks single-layer horizontal fit inside cover + 10 mm stirrup leg."],
    )


@feature(
    "libraryChecks.coverClash",
    "Cover Clash",
    part="objects",
    fields=[number("minRequiredMm", "Minimum nominal cover", 20.0, unit="mm", min=10.0)],
    requires_project=False,
)
def cover_clash(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect reinforcement definitions whose cover falls below minimum threshold or exceeds half thickness."""
    lib, _ = objects_or_default(ctx)
    rows = []
    clashes = 0
    for obj in lib.objects:
        reinf = getattr(obj, "reinforcement", None)
        if reinf is None:
            continue
        cov = float(reinf.cover)
        half_dim = float(getattr(obj, "thickness", 400.0)) / 2.0
        prof = getattr(obj, "profile", None)
        if isinstance(prof, o.RectangleProfile):
            half_dim = min(prof.xDim, prof.yDim) / 2.0
        ok = values["minRequiredMm"] <= cov < half_dim
        if not ok:
            clashes += 1
        rows.append(
            {"id": obj.id, "kind": obj.kind, "coverMm": cov, "halfDimMm": half_dim, "ok": ok}
        )
    return result(
        summary={"checkedTypes": len(rows), "coverClashes": clashes, "allClear": clashes == 0},
        tables=[
            table(
                "Cover envelope clash check",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("coverMm", "Cover", "mm"),
                    ("halfDimMm", "Half dim", "mm"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Flags covers below minimum or encroaching past section centreline."],
    )


@feature(
    "libraryChecks.lapZoneCheck",
    "Lap Zone Check",
    part="objects",
    fields=[number("storeyClearMm", "Typical storey clear height", 3000.0, unit="mm", min=1500.0)],
    requires_project=False,
)
def lap_zone_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify tension lap lengths of column and wall types fit inside permitted central splice zones."""
    from saengine.drawings.detailing import column_lap, column_splice_region

    lib, _ = objects_or_default(ctx)
    with in_force(ctx.root):
        z0, z1 = column_splice_region(values["storeyClearMm"])
        zone_len = z1 - z0
    rows = []
    fails = 0
    for obj in lib.objects:
        if obj.kind != "column":
            continue
        reinf = getattr(obj, "reinforcement", None)
        if reinf is None or not reinf.longitudinal:
            continue
        max_dia = max(g.dia for g in reinf.longitudinal)
        with in_force(ctx.root):
            lap = column_lap(max_dia, 420.0, 25.0).value
        ok = lap <= zone_len
        if not ok:
            fails += 1
        rows.append(
            {"id": obj.id, "maxDiaMm": max_dia, "lapMm": lap, "zoneLenMm": zone_len, "ok": ok}
        )
    return result(
        summary={"checkedColumns": len(rows), "zoneLenMm": zone_len, "lapZoneFailures": fails},
        tables=[
            table(
                "Column central splice zone check",
                [
                    ("id", "ID"),
                    ("maxDiaMm", "Max dia", "mm"),
                    ("lapMm", "Lap len", "mm"),
                    ("zoneLenMm", "Zone len", "mm"),
                    ("ok", "Fits"),
                ],
                rows,
            )
        ],
        notes=["Compares column tension lap length against middle-half permitted splice region."],
    )


@feature(
    "libraryChecks.strengthMismatch",
    "Strength Mismatch",
    part="objects",
    fields=[
        number("minStructuralFcMpa", "Minimum structural concrete f'c", 20.0, unit="MPa", min=10.0)
    ],
    requires_project=False,
)
def strength_mismatch(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Flag structural concrete object types whose material grade falls below minimum structural strength."""
    lib, _ = objects_or_default(ctx)
    mats, _ = materials_or_default(ctx)
    rows = []
    mismatches = 0
    for obj in lib.objects:
        mat = mats.get(obj.material)
        if mat is None or mat.concrete is None:
            continue
        structural = getattr(obj, "structural", True)
        fc = float(mat.concrete.fc)
        ok = (not structural) or (fc >= values["minStructuralFcMpa"])
        if not ok:
            mismatches += 1
        rows.append(
            {
                "id": obj.id,
                "kind": obj.kind,
                "material": mat.id,
                "fcMpa": fc,
                "structural": structural,
                "ok": ok,
            }
        )
    return result(
        summary={
            "checkedConcreteTypes": len(rows),
            "mismatches": mismatches,
            "allCompliant": mismatches == 0,
        },
        tables=[
            table(
                "Concrete grade adequacy audit",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("material", "Material"),
                    ("fcMpa", "f'c", "MPa"),
                    ("structural", "Structural"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[
            "Checks every structural concrete member type against minimum required cylinder strength f'c."
        ],
    )


@feature(
    "libraryChecks.densityCheck",
    "Density Check",
    part="objects",
    fields=[],
    requires_project=False,
)
def density_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare assigned material densities on object types against standard category ranges."""
    lib, _ = objects_or_default(ctx)
    mats, _ = materials_or_default(ctx)
    ranges = {"concrete": (2200.0, 2600.0), "steel": (7700.0, 8000.0), "masonry": (1600.0, 2200.0)}
    rows = []
    outliers = 0
    for obj in lib.objects:
        mat = mats.get(obj.material)
        if mat is None:
            continue
        rho = float(mat.mechanical.density)
        lo, hi = ranges.get(mat.category.value, (500.0, 9000.0))
        ok = lo <= rho <= hi
        if not ok:
            outliers += 1
        rows.append(
            {
                "id": obj.id,
                "material": mat.id,
                "category": mat.category.value,
                "densityKgM3": rho,
                "ok": ok,
            }
        )
    return result(
        summary={"checkedTypes": len(rows), "densityOutliers": outliers},
        tables=[
            table(
                "Object material density audit",
                [
                    ("id", "ID"),
                    ("material", "Material"),
                    ("category", "Category"),
                    ("densityKgM3", "Density", "kg/m3"),
                    ("ok", "In range"),
                ],
                rows,
            )
        ],
        notes=[
            "Verifies concrete (2200-2600 kg/m3), steel (7700-8000 kg/m3), and masonry (1600-2200 kg/m3) densities."
        ],
    )


@feature(
    "libraryChecks.unitWeightCheck",
    "Unit Weight Check",
    part="objects",
    fields=[],
    requires_project=False,
)
def unit_weight_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute linear or areal self-weight of every object type from its section geometry and unit weight."""
    lib, _ = objects_or_default(ctx)
    mats, _ = materials_or_default(ctx)
    rows = []
    for obj in lib.objects:
        mat = mats.get(obj.material)
        rho = float(mat.mechanical.density) if mat else 2400.0
        gamma = rho * 9.81 / 1000.0  # kN/m3
        prof = getattr(obj, "profile", None)
        if prof is not None and not (isinstance(prof, o.DesignedProfile) and ctx.root is None):
            props = section_properties(prof)
            wt = props.area * 1e-6 * gamma
            unit = "kN/m"
        elif getattr(obj, "thickness", None) is not None:
            wt = (float(obj.thickness) / 1000.0) * gamma
            unit = "kN/m2"
        else:
            continue
        rows.append(
            {
                "id": obj.id,
                "kind": obj.kind,
                "unitWeightKnM3": gamma,
                "selfWeight": wt,
                "unit": unit,
            }
        )
    return result(
        summary={"checkedTypes": len(rows)},
        tables=[
            table(
                "Object self-weight audit",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("unitWeightKnM3", "gamma", "kN/m3"),
                    ("selfWeight", "Self-weight"),
                    ("unit", "Unit"),
                ],
                rows,
            )
        ],
        notes=[
            "Self-weight derived from profile area or panel thickness times material unit weight."
        ],
    )


@feature(
    "libraryChecks.orphanTypes",
    "Orphan Types",
    part="objects",
    fields=[],
    requires_project=True,
)
def orphan_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List object types in 04 Objects that are not placed anywhere in BIM or Floor Plan."""
    lib = require_objects(ctx)
    usages = used_type_ids(ctx)
    rows = [
        {"id": obj.id, "name": obj.name, "kind": obj.kind, "material": obj.material}
        for obj in lib.objects
        if usages.get(obj.id, 0) == 0
    ]
    return result(
        summary={"totalTypes": len(lib.objects), "orphanCount": len(rows)},
        tables=[
            table(
                "Unreferenced (orphan) object types",
                [("id", "ID"), ("name", "Name"), ("kind", "Kind"), ("material", "Material")],
                rows or [{"id": "-", "name": "No orphan types", "kind": "-", "material": "-"}],
            )
        ],
        notes=["Compares 04 Objects against 06 BIM and 05 Floor Plan placements."],
    )


@feature(
    "libraryChecks.versionDrift",
    "Version Drift",
    part="objects",
    fields=[],
    requires_project=True,
)
def version_drift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare object/material/BIM SHA stamps in 10 BOQ or 06 BIM against current library files."""
    import hashlib

    require_root(ctx, "checking library version drift")
    rows = []
    boq = ctx.raw("boq") or {}
    boq_src = boq.get("source") or {}
    for label, rel, key in [
        ("04 Objects", "04 Objects/objects.json", "objects"),
        ("03 Materials", "03 Materials/materials.json", "materials"),
        ("06 BIM", "06 BIM/bim.json", "bim"),
    ]:
        p = ctx.path(rel)
        if p is not None and p.is_file():
            cur_hash = hashlib.sha1(p.read_bytes(), usedforsecurity=False).hexdigest()[:12]
            recorded = str(boq_src.get(key, ""))[:12]
            drifted = bool(recorded and recorded != cur_hash)
            rows.append(
                {
                    "file": label,
                    "currentHash": cur_hash,
                    "boqStamp": recorded or "none",
                    "drifted": drifted,
                }
            )
    return result(
        summary={"checkedFiles": len(rows), "driftedFiles": sum(1 for r in rows if r["drifted"])},
        tables=[
            table(
                "Library version drift check",
                [
                    ("file", "File"),
                    ("currentHash", "Current SHA1"),
                    ("boqStamp", "BOQ stamp"),
                    ("drifted", "Drifted"),
                ],
                rows,
            )
        ],
        notes=["Compares current file hashes with the source stamps saved in 10 BOQ/boq.json."],
    )


@feature(
    "libraryChecks.librarySnapshot",
    "Library Snapshot",
    part="objects",
    fields=[text("snapshotName", "Snapshot file name", "objects-snapshot.json")],
    requires_project=True,
)
def library_snapshot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Capture a timestamped JSON snapshot of 04 Objects/objects.json under 04 Objects/exports."""
    lib = require_objects(ctx)
    fname = values["snapshotName"].strip() or "objects-snapshot.json"
    if not fname.lower().endswith(".json"):
        fname += ".json"
    payload = lib.model_dump(mode="json", by_alias=True, exclude_none=True)
    target = save_export(ctx, fname, safe_json(payload))
    return result(
        summary={"typeCount": len(lib.objects), "snapshotPath": str(target)},
        tables=[
            table(
                "Snapshot manifest",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Snapshot path", "value": str(target)},
                    {"item": "Object types", "value": len(lib.objects)},
                ],
            )
        ],
        notes=[f"Saved snapshot of {len(lib.objects)} object types to {target}."],
    )
