"""Thin JSON-RPC handlers for SAEngine U6d engine panels (no new math; delegates to domain modules).

Never raises across the JSON-RPC boundary: validation or missing-input errors return a dict with
``problems`` and/or ``notes`` so the UI data panels can display clear guidance.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _first_line(error: BaseException) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _finite(value: Any) -> Any:
    from saengine.plumbing.project import finite

    return finite(value)


def _project_path(project_root: str, rel: str) -> Path:
    return Path(project_root) / rel


# ────────────────────────────────────────── Soil Report ──────────────────────────────────────────


def soil_analysis(project_root: str) -> dict[str, Any]:
    """Full soil report analysis (boreholes, SPT, lab, bearing, liquefaction, chemistry, investigation)."""
    from saengine.soil.report import soil_report

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json")
    if not soil_text:
        return {
            "boreholes": [],
            "investigation": {
                "checks": [],
                "notes": ["01 Soil Report/soil-report.json not found."],
            },
            "chemistry": {"samples": [], "concrete": None},
            "stratigraphy": {"units": [], "boreholes": [], "fences": [], "notes": []},
            "siteClass": {"class": None, "boreholes": 0, "label": "None", "note": ""},
            "notes": ["01 Soil Report/soil-report.json not found."],
            "warnings": [],
            "problems": [],
        }
    settings_text = _read_text(root / "02 Project Settings/project-settings.json")
    try:
        res = soil_report(soil_text, settings_text)
        return _finite(res)
    except Exception as error:  # noqa: BLE001
        return {"boreholes": [], "notes": [], "problems": [_first_line(error)]}


def soil_bearing_check(
    project_root: str,
    *,
    x: float = 0.0,
    y: float = 0.0,
    founding_level: float = -1500.0,
    b: float = 2000.0,
    l: float = 2000.0,
) -> dict[str, Any]:
    """Net allowable bearing pressure of a spread footing from the project's soil report."""
    from saengine.soil.report import allowable_bearing

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json") or "{}"
    settings_text = _read_text(root / "02 Project Settings/project-settings.json")
    try:
        res = allowable_bearing(
            soil_text,
            settings_text,
            float(x),
            float(y),
            float(founding_level),
            float(b),
            float(l),
        )
        return _finite(res)
    except Exception as error:  # noqa: BLE001
        return {"qa_kpa": None, "notes": [], "problems": [_first_line(error)]}


def soil_settlement_check(
    project_root: str,
    *,
    borehole: str | None = None,
    b: float = 2000.0,
    l: float = 2000.0,
    df: float = 1500.0,
    q: float = 150.0,
    foundation: str = "isolated",
) -> dict[str, Any]:
    """Immediate + consolidation settlement check for a footing at a borehole."""
    from saengine.soil.report import footing_settlement, parse_boreholes

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json") or "{}"
    try:
        parsed, _probs, _skipped = parse_boreholes(soil_text)
        bh_ids = [bh.id for bh in parsed.boreholes] if parsed else []
        target = borehole if borehole and borehole in bh_ids else (bh_ids[0] if bh_ids else None)
        if not target:
            return {
                "borehole": None,
                "availableBoreholes": [],
                "notes": ["Add at least one borehole to 01 Soil Report to compute settlement."],
                "problems": [],
            }
        res = footing_settlement(
            soil_text,
            target,
            float(b),
            float(l),
            float(df),
            float(q),
            foundation if foundation in ("isolated", "raft") else "isolated",
        )
        return _finite(
            {
                **res,
                "borehole": target,
                "availableBoreholes": bh_ids,
                "problems": list(res.get("problems") or []),
            }
        )
    except Exception as error:  # noqa: BLE001
        return {"borehole": borehole, "availableBoreholes": [], "problems": [_first_line(error)]}


def soil_characteristic_bearing(
    project_root: str,
    *,
    borehole: str | None = None,
    fak: float = 150.0,
    b: float = 2.0,
    l: float = 2.0,
    df: float = 1.5,
    q: float = 150.0,
) -> dict[str, Any]:
    """Width/depth-corrected characteristic bearing value and layerwise settlement (code pack dependent)."""
    from saengine.report.clauses import in_force
    from saengine.soil import characteristic_bearing as cb
    from saengine.soil.profile import Profile
    from saengine.soil.report import parse_boreholes

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json") or "{}"
    notes: list[str] = []
    problems: list[str] = []
    try:
        with in_force(root) as pack_problems:
            problems.extend(pack_problems)
            corr = cb.corrected(float(fak), float(b), float(df))
            fa_kpa: float | None = None
            corr_note = (
                "The active code pack has no width/depth characteristic bearing correction rule."
            )
            if corr is not None:
                fa_kpa, corr_note = corr
            notes.append(corr_note)

            parsed, parse_probs, _skipped = parse_boreholes(soil_text)
            problems.extend(parse_probs)
            bh_ids = [bh.id for bh in parsed.boreholes] if parsed else []
            target = (
                borehole if borehole and borehole in bh_ids else (bh_ids[0] if bh_ids else None)
            )

            layerwise: dict[str, Any] | None = None
            if cb.settlement_rule() is None:
                notes.append("The active code pack has no layerwise settlement rule.")
            elif parsed is not None and target is not None:
                bh = next((h for h in parsed.boreholes if h.id == target), None)
                if bh is not None:
                    profile = Profile(parsed, bh)
                    layerwise = cb.layerwise_settlement(
                        profile, float(b), float(l), float(df), float(q)
                    )
                    notes.extend(layerwise.get("notes") or [])
            return _finite(
                {
                    "borehole": target,
                    "availableBoreholes": bh_ids,
                    "fakKpa": float(fak),
                    "faKpa": round(fa_kpa, 2) if fa_kpa is not None else None,
                    "correctionNote": corr_note,
                    "layerwise": layerwise,
                    "notes": notes,
                    "problems": problems,
                }
            )
    except Exception as error:  # noqa: BLE001
        return {"faKpa": None, "layerwise": None, "notes": notes, "problems": [_first_line(error)]}


def soil_earth_pressure(
    project_root: str,
    *,
    borehole: str | None = None,
    depth_m: float = 6.0,
    surcharge_kpa: float = 10.0,
    water_table_m: float | None = None,
    phi_deg: float = 30.0,
    gamma: float = 18.0,
    kh: float = 0.0,
    beta_deg: float = 0.0,
    delta_deg: float = 0.0,
) -> dict[str, Any]:
    """Lateral earth pressure coefficients (Rankine, Jaky, Coulomb, Mononobe-Okabe) and depth profile."""
    from saengine.soil import earth_pressure as soil_ep
    from saengine.soil.profile import Profile
    from saengine.soil.report import parse_boreholes
    from saengine.substructure import earth_pressure as sub_ep

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json") or "{}"
    notes: list[str] = []
    problems: list[str] = []
    try:
        phi = max(1.0, min(55.0, float(phi_deg)))
        beta = max(0.0, min(phi - 0.1, float(beta_deg)))
        delta = max(0.0, min(phi, float(delta_deg)))
        kh_val = max(0.0, float(kh))
        depth = max(0.5, float(depth_m))
        q = max(0.0, float(surcharge_kpa))

        ka_rank = soil_ep.rankine_active(phi)
        kp_rank = soil_ep.rankine_passive(phi)
        k0 = sub_ep.k0_jaky(phi)
        ka_slope = sub_ep.ka_rankine(phi, beta)
        kp_slope = sub_ep.kp_rankine(phi, beta)
        ka_coul = sub_ep.ka_coulomb(phi, delta, beta)
        kp_coul = sub_ep.kp_coulomb(phi, delta)
        kae_mo = sub_ep.kae_mononobe_okabe(phi, kh_val, 0.0, delta, beta) if kh_val > 0 else ka_coul

        parsed, parse_probs, _skipped = parse_boreholes(soil_text)
        problems.extend(parse_probs)
        profiles: list[Profile] = []
        bh_ids: list[str] = []
        if parsed and parsed.boreholes:
            bh_ids = [b.id for b in parsed.boreholes]
            chosen = (
                [b for b in parsed.boreholes if b.id == borehole] if borehole else parsed.boreholes
            )
            if not chosen:
                chosen = parsed.boreholes
            profiles = [Profile(parsed, b) for b in chosen]

        wt = float(water_table_m) if water_table_m is not None and water_table_m >= 0 else None
        if profiles:
            soil_col = sub_ep.soil_column(
                profiles,
                float(profiles[0].borehole.x),
                float(profiles[0].borehole.y),
                water_table=wt,
                surcharge=q,
            )
            bh_used = profiles[0].id
        else:
            soil_col = sub_ep.soil_column(
                [],
                0.0,
                0.0,
                water_table=wt,
                surcharge=q,
                override={"phi": phi, "gamma": float(gamma), "c": 0.0},
            )
            bh_used = "Entered parameters"
            notes.append("No boreholes in 01 Soil Report: using entered φ' and γ parameters.")

        steps = 8
        profile_rows: list[dict[str, Any]] = []
        for i in range(steps + 1):
            z = round(depth * i / steps, 2)
            pa = soil_col.pressure(z, "active", water=True)
            p0 = soil_col.pressure(z, "atRest", water=True)
            pp = soil_col.pressure(z, "passive", water=True)
            profile_rows.append(
                {
                    "z": z,
                    # total vertical stress and pore pressure from the column itself
                    # (pressure() returns K, soil, surcharge, water and total only)
                    "sigmaV": round(soil_col.sigma_v(z), 2),
                    "u": round(soil_col.u(z), 2),
                    "active": round(pa.get("total", 0.0), 2),
                    "atRest": round(p0.get("total", 0.0), 2),
                    "passive": round(pp.get("total", 0.0), 2),
                }
            )

        seis_inc = (
            sub_ep.seismic_increment(soil_col, depth, kh_val, yielding=True, beta=beta, delta=delta)
            if kh_val > 0
            else None
        )
        return _finite(
            {
                "borehole": bh_used,
                "availableBoreholes": bh_ids,
                "source": soil_col.source,
                "coefficients": {
                    "k0Jaky": round(k0, 4),
                    "kaRankine": round(ka_rank, 4),
                    "kpRankine": round(kp_rank, 4),
                    "kaRankineSloped": round(ka_slope, 4),
                    "kpRankineSloped": round(kp_slope, 4),
                    "kaCoulomb": round(ka_coul, 4),
                    "kpCoulomb": round(kp_coul, 4),
                    "kaeMononobeOkabe": round(kae_mo, 4),
                },
                "profile": profile_rows,
                "seismic": seis_inc,
                "notes": notes,
                "problems": problems,
            }
        )
    except Exception as error:  # noqa: BLE001
        return {"coefficients": {}, "profile": [], "notes": notes, "problems": [_first_line(error)]}


def soil_plot_planning(project_root: str) -> dict[str, Any]:
    """Combined site location, plot/setback encroachment check, and FAR/MGC planning compliance."""
    from saengine.gis import planning, plot, site
    from saengine.soil.report import parse

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json")
    bim_text = _read_text(root / "06 BIM/bim.json")
    settings_text = _read_text(root / "02 Project Settings/project-settings.json")
    fp_text = _read_text(root / "05 Floor Plan/floor-plan.json")
    obj_text = _read_text(root / "04 Objects/objects.json")

    notes: list[str] = []
    problems: list[str] = []
    try:
        loc = site.soil_location(soil_text, bim_text, settings_text)
        report = parse(soil_text or "{}")
        plot_res: dict[str, Any] | None = None
        plan_res: dict[str, Any] | None = None
        if isinstance(report, list):
            problems.extend(report)
        else:
            plot_res = plot.encroachments(report.site, fp_text, obj_text)
            plan_res = planning.check(report.site, bim_text, settings_text)
            if plot_res and plot_res.get("notes"):
                notes.extend(plot_res["notes"])
            if plan_res and plan_res.get("notes"):
                notes.extend(plan_res["notes"])
        return _finite(
            {
                "location": loc,
                "plot": plot_res,
                "planning": plan_res,
                "notes": notes,
                "problems": problems,
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "location": None,
            "plot": None,
            "planning": None,
            "notes": notes,
            "problems": [_first_line(error)],
        }


def soil_sources_check(project_root: str) -> dict[str, Any]:
    """Where active site class and allowable bearing pressure come from (soil report vs overrides)."""
    from saengine.rpc import handlers

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json")
    settings_text = _read_text(root / "02 Project Settings/project-settings.json")
    try:
        return _finite(handlers.soil_sources(soil_text, settings_text))
    except Exception as error:  # noqa: BLE001
        return {"problems": [_first_line(error)]}


# ────────────────────────────────────────── Settings & Codes ──────────────────────────────────────────


def codes_conformance(
    project_root: str | None = None, *, pack_id: str | None = None
) -> dict[str, Any]:
    """Run all 7 conformance checks on the active or selected code pack."""
    from saengine.codes import conformance
    from saengine.codes import context as code_context

    root = Path(project_root) if project_root else None
    settings_data: dict[str, Any] = {}
    if root:
        raw = _read_text(root / "02 Project Settings/project-settings.json")
        if raw:
            try:
                settings_data = json.loads(raw)
            except ValueError:
                settings_data = {}
    if pack_id:
        settings_data = {**settings_data, "codePack": pack_id}
    try:
        with code_context.project(root):
            pack = code_context.pack_for(settings_data, root)
            findings = conformance.check_pack(pack)
        errs = [f for f in findings if f.level == "error"]
        warns = [f for f in findings if f.level != "error"]
        return _finite(
            {
                "packId": pack.id,
                "packName": pack.edition or pack.name,
                "ok": len(errs) == 0,
                "checks": list(conformance.CHECKS),
                "errorCount": len(errs),
                "warningCount": len(warns),
                "findings": [f.as_dict() for f in findings],
                "problems": [],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "findings": [], "problems": [_first_line(error)]}


def codes_diff(pack_a: str, pack_b: str, *, project_root: str | None = None) -> dict[str, Any]:
    """Compare resolved tables of two code packs side by side."""
    from saengine.codes.template import diff_packs

    root = Path(project_root) if project_root else None
    try:
        diffs = diff_packs(pack_a, pack_b, root)
        rows = [
            {
                "path": d.path,
                "table": d.path.split(".", 1)[0],
                "kind": d.kind,
                "a": d.a,
                "b": d.b,
            }
            for d in diffs
        ]
        return _finite(
            {
                "packA": pack_a,
                "packB": pack_b,
                "count": len(rows),
                "differences": rows,
                "problems": [],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "packA": pack_a,
            "packB": pack_b,
            "count": 0,
            "differences": [],
            "problems": [_first_line(error)],
        }


def settings_hazard_summary(project_root: str) -> dict[str, Any]:
    """Derived seismic & wind parameters, soil sources, and available online hazard providers."""
    from saengine.gis import hazard_lookup
    from saengine.library.settings import ProjectSettings, default_project_settings, derived
    from saengine.rpc import handlers

    root = Path(project_root)
    settings_text = _read_text(root / "02 Project Settings/project-settings.json")
    soil_text = _read_text(root / "01 Soil Report/soil-report.json")
    notes: list[str] = []
    problems: list[str] = []
    try:
        if settings_text:
            try:
                settings = ProjectSettings.model_validate_json(settings_text)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"Project settings validation: {_first_line(exc)}")
                settings = default_project_settings()
        else:
            settings = default_project_settings()
            notes.append(
                "Using default project settings (02 Project Settings/project-settings.json not found)."
            )
        der = derived(settings)
        sources = handlers.soil_sources(soil_text, settings_text)
        offers = hazard_lookup.offers(settings_text, soil_text, str(root))
        return _finite(
            {
                "derived": der,
                "sources": sources,
                "offers": offers,
                "notes": notes,
                "problems": problems,
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "derived": {},
            "sources": {},
            "offers": {},
            "notes": notes,
            "problems": [_first_line(error)],
        }


def settings_towns(project_root: str | None = None) -> dict[str, Any]:
    """List towns from the active code pack's hazard tables (seismic zone Z and wind speed V)."""
    from saengine.gis import towns
    from saengine.report.clauses import in_force

    try:
        ctx = in_force(project_root) if project_root else None
        if ctx is not None:
            with ctx as pack_problems:
                rows = towns.towns()
                return _finite({"towns": rows, "problems": list(pack_problems)})
        return _finite({"towns": towns.towns(), "problems": []})
    except Exception as error:  # noqa: BLE001
        return {"towns": [], "problems": [_first_line(error)]}


# ────────────────────────────────────────── Library ──────────────────────────────────────────


def library_material_summary(
    project_root: str, *, fc: float = 28.0, mix_ratio: str = "1:2:4"
) -> dict[str, Any]:
    """Project material properties, concrete modulus/rupture, nominal mix, plausibility and code bar sizes."""
    from saengine.codes import bars
    from saengine.library import materials as mat_lib
    from saengine.report.clauses import in_force

    root = Path(project_root)
    mat_text = _read_text(root / "03 Materials/materials.json")
    problems: list[str] = []
    notes: list[str] = []
    try:
        with in_force(root) as pack_problems:
            problems.extend(pack_problems)
            rows: list[dict[str, Any]] = []
            if mat_text:
                lib = mat_lib.MaterialLibrary.model_validate_json(mat_text)
                for m in lib.materials:
                    plaus = mat_lib.plausibility(m)
                    fc_val = float(m.concrete.fc) if m.concrete is not None else None
                    rows.append(
                        {
                            "id": m.id,
                            "category": m.category,
                            "name": m.name or m.id,
                            "density": m.mechanical.density,
                            "e": m.mechanical.E,
                            "nu": m.mechanical.nu,
                            "fc": fc_val,
                            "fy": float(m.rebar.fy)
                            if m.rebar
                            else (float(m.steel.fy) if m.steel else None),
                            "ecCalc": round(mat_lib.concrete_modulus(fc_val), 1)
                            if fc_val
                            else None,
                            "frCalc": round(mat_lib.modulus_of_rupture(fc_val), 2)
                            if fc_val
                            else None,
                            "warnings": "; ".join(f"{w[0]}: {w[1]}" for w in plaus)
                            if plaus
                            else "OK",
                        }
                    )
            else:
                notes.append("03 Materials/materials.json not found.")

            fc_in = max(1.0, float(fc))
            ratio_parts = [float(p) for p in mix_ratio.replace(",", ":").split(":") if p.strip()]
            mix_fc = mat_lib.nominal_mix_strength(ratio_parts) if len(ratio_parts) == 3 else None
            bar_masses = bars.pack_bar_masses()
            bar_rows = [
                {"diameterMm": d, "massKgPerM": mass} for d, mass in sorted(bar_masses.items())
            ]
            return _finite(
                {
                    "materials": rows,
                    "calculator": {
                        "fc": fc_in,
                        "ecMpa": round(mat_lib.concrete_modulus(fc_in), 1),
                        "frMpa": round(mat_lib.modulus_of_rupture(fc_in), 2),
                        "mixRatio": mix_ratio,
                        "nominalMixFc": round(mix_fc, 1) if mix_fc is not None else None,
                    },
                    "barSizes": bar_rows,
                    "notes": notes,
                    "problems": problems,
                }
            )
    except Exception as error:  # noqa: BLE001
        return {"materials": [], "barSizes": [], "notes": notes, "problems": [_first_line(error)]}


def library_object_sections(project_root: str) -> dict[str, Any]:
    """Geometric section properties and stiffness modifiers for every object type (and member overrides)."""
    from saengine.library import modifiers, sections
    from saengine.library.floorplan import FloorPlan
    from saengine.library.objects import ObjectLibrary

    root = Path(project_root)
    obj_text = _read_text(root / "04 Objects/objects.json")
    fp_text = _read_text(root / "05 Floor Plan/floor-plan.json")
    notes: list[str] = []
    problems: list[str] = []
    if not obj_text:
        return {
            "objects": [],
            "modifiers": [],
            "notes": ["04 Objects/objects.json not found."],
            "problems": [],
        }
    try:
        lib = ObjectLibrary.model_validate_json(obj_text)
        obj_map = {o.id: o for o in lib.objects}
        obj_rows: list[dict[str, Any]] = []
        mod_rows: list[dict[str, Any]] = []
        for obj in lib.objects:
            prof = getattr(obj, "profile", None)
            props: dict[str, Any] = {}
            if prof is not None:
                try:
                    sp = sections.section_properties(prof)
                    props = {
                        "areaMm2": round(sp.area, 1),
                        "ixMm4": round(sp.ix, 1),
                        "iyMm4": round(sp.iy, 1),
                        "jMm4": round(sp.j, 1),
                        "rxMm": round(sp.rx, 1),
                        "ryMm": round(sp.ry, 1),
                        "zxMm3": round(sp.zx, 1),
                        "zyMm3": round(sp.zy, 1),
                    }
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"{obj.id}: section properties skipped ({_first_line(exc)})")
            mods = modifiers.modifiers_of(obj)
            obj_rows.append(
                {
                    "id": obj.id,
                    "kind": obj.kind,
                    "material": getattr(obj, "material", "") or "",
                    "shape": getattr(prof, "shape", "") if prof else "",
                    **props,
                    "modifiersCount": len(mods),
                }
            )
            if mods:
                mod_rows.append(
                    {
                        "target": obj.id,
                        "scope": "Object Type",
                        "kind": obj.kind,
                        **{k: v for k, v in mods.items()},
                    }
                )

        if fp_text:
            try:
                fp = FloorPlan.model_validate_json(fp_text)
                for member in [*fp.beams, *fp.columns, *fp.walls, *fp.slabs]:
                    otype = obj_map.get(member.type)
                    resolved = modifiers.resolve_modifiers(member, otype)
                    if resolved:
                        mod_rows.append(
                            {
                                "target": member.id,
                                "scope": "Member",
                                "kind": member.type,
                                **{k: f"{v} ({src})" for k, (v, src) in resolved.items()},
                            }
                        )
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Floor plan modifiers skipped: {_first_line(exc)}")

        return _finite(
            {"objects": obj_rows, "modifiers": mod_rows, "notes": notes, "problems": problems}
        )
    except Exception as error:  # noqa: BLE001
        return {"objects": [], "modifiers": [], "notes": notes, "problems": [_first_line(error)]}


def library_designed_sections(
    project_root: str,
    *,
    section_id: str | None = None,
    capacity: bool = True,
    moment_curvature: bool = False,
    axial_kn: float = 0.0,
) -> dict[str, Any]:
    """List designed sections (`04 Objects/sections/*.json`) and optionally run fibre capacity/M-κ."""
    from saengine.library import section_designer as sd
    from saengine.library.materials import MaterialLibrary

    root = Path(project_root)
    mat_text = _read_text(root / "03 Materials/materials.json")
    notes: list[str] = []
    problems: list[str] = []
    try:
        ids = sd.list_sections(root)
        materials = MaterialLibrary.model_validate_json(mat_text) if mat_text else MaterialLibrary()
        inventory: list[dict[str, Any]] = []
        for sid in ids:
            sec = sd.load_section(root, sid)
            g_probs = sd.geometry_problems(sec)
            props = None
            if not g_probs:
                try:
                    sp = sd.properties(sec, materials)
                    props = {
                        "area": round(sp.area, 1),
                        "ix": round(sp.ix, 1),
                        "iy": round(sp.iy, 1),
                    }
                except Exception as exc:  # noqa: BLE001
                    g_probs = [_first_line(exc)]
            inventory.append(
                {
                    "id": sid,
                    "regions": len(sec.regions),
                    "bars": len(sec.bars),
                    "areaMm2": props["area"] if props else None,
                    "ixMm4": props["ix"] if props else None,
                    "iyMm4": props["iy"] if props else None,
                    "status": "Fail" if g_probs else "Pass",
                    "note": "; ".join(g_probs) if g_probs else "OK",
                }
            )

        target = section_id if section_id and section_id in ids else (ids[0] if ids else None)
        analysis: dict[str, Any] | None = None
        if target:
            sec_text = _read_text(sd.section_path(root, target))
            if sec_text:
                mc_req = {"axial": float(axial_kn) * 1e3} if moment_curvature else None
                analysis = sd.analyse(
                    sec_text,
                    mat_text,
                    root,
                    capacity=bool(capacity),
                    moment_curvature=mc_req,
                )
        elif not ids:
            notes.append(
                "No designed sections found in 04 Objects/sections/. Use Section Designer to create one."
            )

        return _finite(
            {
                "availableSections": ids,
                "sectionId": target,
                "sections": inventory,
                "analysis": analysis,
                "notes": notes,
                "problems": problems,
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "availableSections": [],
            "sectionId": section_id,
            "sections": [],
            "analysis": None,
            "notes": notes,
            "problems": [_first_line(error)],
        }


def library_sheet_piles(*, shape: str | None = None) -> dict[str, Any]:
    """Steel sheet pile section catalogue (U and Z sections)."""
    from saengine.library import sheet_piles

    rows = [
        {
            "name": s.name,
            "shape": s.shape,
            "widthMm": s.width,
            "heightMm": s.height,
            "wCm3PerM": s.W,
            "iCm4PerM": s.I,
            "massKgPerM2": s.mass,
            "nominal": s.nominal,
        }
        for s in sheet_piles.SECTIONS
        if not shape or shape == "all" or s.shape.upper() == shape.upper()
    ]
    return _finite({"sections": rows, "problems": []})


def library_arch_types(project_root: str, *, category: str | None = None) -> dict[str, Any]:
    """Architectural types library and parametric component starter catalogue / schedule."""
    from saengine.library import architecture as arch_lib
    from saengine.library import components, types_library

    root = Path(project_root)
    arch_text = _read_text(root / arch_lib.ARCHITECTURE_FILE)
    notes: list[str] = []
    try:
        arch = arch_lib.parse(arch_text)
        cat = category if category and category != "all" else None
        types = types_library.list_types(arch, cat)  # type: ignore[arg-type]
        starter = [c.model_dump(mode="json") for c in components.starter_component_types()]
        sched = components.component_schedule(arch)
        if not arch_text:
            notes.append(
                "05 Floor Plan/architecture.json not found; showing starter types and components."
            )
        return _finite(
            {
                "types": types,
                "starterComponents": starter,
                "componentSchedule": sched,
                "notes": notes,
                "problems": [],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "types": [],
            "starterComponents": [],
            "componentSchedule": {},
            "notes": notes,
            "problems": [_first_line(error)],
        }


def library_validate_all(project_root: str) -> dict[str, Any]:
    """Validate 03 Materials and 04 Objects together (references, coverage warnings, code pack rules)."""
    from saengine.library.check import check_library

    root = Path(project_root)
    mat_text = _read_text(root / "03 Materials/materials.json")
    obj_text = _read_text(root / "04 Objects/objects.json")
    set_text = _read_text(root / "02 Project Settings/project-settings.json")
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    try:
        if mat_text:
            for p in check_library("materials", mat_text, None, set_text):
                sev = "Warning" if p.get("severity") == "warning" else "Error"
                rows.append(
                    {
                        "file": "03 Materials",
                        "index": p.get("index"),
                        "path": p.get("path", ""),
                        "message": p.get("message", ""),
                        "severity": sev,
                    }
                )
        else:
            notes.append("03 Materials/materials.json not found.")
        if obj_text:
            for p in check_library("objects", obj_text, mat_text, set_text):
                sev = "Warning" if p.get("severity") == "warning" else "Error"
                rows.append(
                    {
                        "file": "04 Objects",
                        "index": p.get("index"),
                        "path": p.get("path", ""),
                        "message": p.get("message", ""),
                        "severity": sev,
                    }
                )
        else:
            notes.append("04 Objects/objects.json not found.")
        return _finite({"findings": rows, "notes": notes, "problems": []})
    except Exception as error:  # noqa: BLE001
        return {"findings": [], "notes": notes, "problems": [_first_line(error)]}


# ────────────────────────────────────────── Substructure ──────────────────────────────────────────


def substructure_pile_capacity(
    project_root: str,
    *,
    kind: str = "bored",
    head_level_mm: float = -1500.0,
    diameters_mm: list[float] | None = None,
    lengths_m: list[float] | None = None,
) -> dict[str, Any]:
    """Single-pile compression and tension capacity table by diameter and length from soil boreholes."""
    from saengine.substructure import piles

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json")
    if not soil_text:
        return {
            "tables": [],
            "rows": [],
            "notes": ["01 Soil Report/soil-report.json not found."],
            "problems": [],
        }
    try:
        profiles, _report, probs = piles.profiles_of(soil_text)
        if not profiles:
            return {
                "tables": [],
                "rows": [],
                "notes": ["No valid boreholes in soil report."],
                "problems": probs,
            }
        diams = [float(d) for d in (diameters_mm or [450.0, 500.0, 600.0, 750.0])]
        lens_mm = [float(ln) * 1000.0 for ln in (lengths_m or [10.0, 15.0, 20.0, 25.0])]
        flat_rows: list[dict[str, Any]] = []
        for prof in profiles:
            head_depth_m = max(0.0, prof.ground_level - float(head_level_mm) / 1000.0)
            tbl = piles.capacity_table(prof, kind, diams, lens_mm, head_depth_m)
            for row in tbl["rows"]:
                flat_rows.append(
                    {
                        "borehole": prof.id,
                        "diameterMm": row["D"],
                        "lengthM": round(row["L"] / 1000.0, 2),
                        "qsKn": row["Qs"],
                        "qbKn": row["Qb"],
                        "qultKn": row["Qult"],
                        "qaKn": row["Qa"],
                        "taKn": row["Ta"],
                    }
                )
        return _finite({"kind": kind, "rows": flat_rows, "notes": [], "problems": probs})
    except Exception as error:  # noqa: BLE001
        return {"rows": [], "notes": [], "problems": [_first_line(error)]}


def substructure_pile_lateral(
    project_root: str,
    *,
    borehole: str | None = None,
    kind: str = "bored",
    diameter_mm: float = 600.0,
    length_m: float = 18.0,
    head_depth_m: float = 1.5,
    fixity: str = "fixed",
    my_knm: float = 250.0,
    ep_mpa: float = 25000.0,
) -> dict[str, Any]:
    """Lateral pile head stiffness, Broms soil failure capacity Hu, and p-y curve summary."""
    from saengine.substructure import pile_lateral, pile_lateral_soil, piles

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json")
    if not soil_text:
        return {
            "stiffness": None,
            "broms": None,
            "py": [],
            "notes": ["01 Soil Report/soil-report.json not found."],
            "problems": [],
        }
    try:
        profiles, _report, probs = piles.profiles_of(soil_text)
        bh_ids = [p.id for p in profiles]
        prof = next((p for p in profiles if p.id == borehole), profiles[0] if profiles else None)
        if prof is None:
            return {
                "availableBoreholes": [],
                "stiffness": None,
                "broms": None,
                "py": [],
                "notes": ["No valid boreholes."],
                "problems": probs,
            }
        stiff = pile_lateral.head_stiffness(
            prof,
            float(head_depth_m),
            kind,
            float(diameter_mm),
            float(length_m) * 1000.0,
            float(ep_mpa),
            fixity,
            ratio=1.0,
        )
        broms = pile_lateral_soil.broms_capacity(
            prof,
            float(head_depth_m),
            float(diameter_mm) / 1000.0,
            float(length_m),
            fixity,
            float(my_knm),
        )
        py_rules = pile_lateral_soil.py_rules()
        py_rows: list[dict[str, Any]] = []
        if py_rules is not None:
            d_m = float(diameter_mm) / 1000.0
            for frac in (0.1, 0.25, 0.5, 0.75):
                z = float(head_depth_m) + float(length_m) * frac
                layer = prof.layer_at(z)
                if layer is None:
                    continue
                sigma = max(prof.sigma_eff(z), 5.0)
                wet = prof.water_table is not None and z >= prof.water_table
                curve = pile_lateral_soil.py_curve(layer, z, d_m, sigma, wet, py_rules)
                if curve:
                    ys, ps = curve[0], curve[1]
                    py_rows.append(
                        {
                            "zM": round(z, 2),
                            "layer": layer.soil_type,
                            "sigmaEffKpa": round(sigma, 1),
                            "yMaxMm": round(float(ys[-1]) * 1000.0, 2) if len(ys) else 0.0,
                            "pUltKnPerM": round(float(ps[-1]), 2) if len(ps) else 0.0,
                        }
                    )
        return _finite(
            {
                "borehole": prof.id,
                "availableBoreholes": bh_ids,
                "stiffness": stiff,
                "broms": broms,
                "py": py_rows,
                "notes": [],
                "problems": probs,
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "stiffness": None,
            "broms": None,
            "py": [],
            "notes": [],
            "problems": [_first_line(error)],
        }


def substructure_pile_settlement(
    project_root: str,
    *,
    borehole: str | None = None,
    kind: str = "bored",
    diameter_mm: float = 600.0,
    length_m: float = 18.0,
    head_depth_m: float = 1.5,
    load_kn: float = 800.0,
    count: int = 4,
    bg_m: float = 2.4,
    lg_m: float = 2.4,
    modulus_mpa: float = 25000.0,
) -> dict[str, Any]:
    """Single-pile elastic/tip/shaft settlement and pile-group equivalent raft settlement."""
    from saengine.substructure import pile_settlement, piles

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json")
    if not soil_text:
        return {
            "single": None,
            "group": None,
            "notes": ["01 Soil Report/soil-report.json not found."],
            "problems": [],
        }
    try:
        profiles, _report, probs = piles.profiles_of(soil_text)
        bh_ids = [p.id for p in profiles]
        prof = next((p for p in profiles if p.id == borehole), profiles[0] if profiles else None)
        if prof is None:
            return {
                "availableBoreholes": [],
                "single": None,
                "group": None,
                "notes": ["No valid boreholes."],
                "problems": probs,
            }
        sp = piles.single_pile(
            prof, kind, float(diameter_mm) / 1000.0, float(length_m), float(head_depth_m)
        )
        single_res = pile_settlement.single_settlement(sp, float(load_kn), prof, float(modulus_mpa))
        group_res = pile_settlement.group_settlement(
            prof,
            sp,
            max(1, int(count)),
            float(bg_m),
            float(lg_m),
            float(load_kn) * max(1, int(count)),
            float(modulus_mpa),
        )
        return _finite(
            {
                "borehole": prof.id,
                "availableBoreholes": bh_ids,
                "pile": sp,
                "single": single_res,
                "group": group_res,
                "notes": [],
                "problems": probs,
            }
        )
    except Exception as error:  # noqa: BLE001
        return {"single": None, "group": None, "notes": [], "problems": [_first_line(error)]}


def substructure_downdrag(
    project_root: str,
    *,
    borehole: str | None = None,
    kind: str = "bored",
    diameter_mm: float = 600.0,
    length_m: float = 18.0,
    head_depth_m: float = 1.5,
    sustained_kn: float = 600.0,
    settling_depth_m: float | None = None,
) -> dict[str, Any]:
    """Negative skin friction (neutral point and dragload) and swelling soil uplift check."""
    from saengine.substructure import downdrag, piles

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json")
    if not soil_text:
        return {
            "neutralPoint": None,
            "swelling": None,
            "notes": ["01 Soil Report/soil-report.json not found."],
            "problems": [],
        }
    try:
        profiles, _report, probs = piles.profiles_of(soil_text)
        bh_ids = [p.id for p in profiles]
        prof = next((p for p in profiles if p.id == borehole), profiles[0] if profiles else None)
        if prof is None:
            return {
                "availableBoreholes": [],
                "neutralPoint": None,
                "swelling": None,
                "notes": ["No valid boreholes."],
                "problems": probs,
            }
        sp = piles.single_pile(
            prof, kind, float(diameter_mm) / 1000.0, float(length_m), float(head_depth_m)
        )
        s_depth, s_note = downdrag.settling_depth(prof, settling_depth_m)
        np_res = (
            downdrag.neutral_point(prof, sp, float(sustained_kn), s_depth)
            if s_depth is not None and s_depth > 0
            else None
        )
        e_depth, e_note = downdrag.expansive_depth(prof, None)
        sw_res = (
            downdrag.swelling(prof, sp, e_depth) if e_depth is not None and e_depth > 0 else None
        )
        notes = [n for n in (s_note, e_note) if n]
        if np_res is None and sw_res is None:
            notes.append(
                "No compressible settling zone or expansive clay layer identified at this borehole."
            )
        return _finite(
            {
                "borehole": prof.id,
                "availableBoreholes": bh_ids,
                "settlingDepthM": s_depth,
                "expansiveDepthM": e_depth,
                "neutralPoint": np_res,
                "swelling": sw_res,
                "notes": notes,
                "problems": probs,
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "neutralPoint": None,
            "swelling": None,
            "notes": [],
            "problems": [_first_line(error)],
        }


def substructure_load_tests(
    project_root: str,
    *,
    diameter_mm: float = 600.0,
    length_m: float = 18.0,
    ep_mpa: float = 25000.0,
    curve_text: str | None = None,
) -> dict[str, Any]:
    """Interpret saved pile load tests and optional load:settlement curve (Davisson, Butler-Hoy, Brinch Hansen)."""
    from saengine.library.substructure import PileLoadTest, Substructure
    from saengine.substructure import load_tests

    root = Path(project_root)
    sub_text = _read_text(root / "09 Substructure/substructure.json")
    project_results: list[dict[str, Any]] = []
    notes: list[str] = []
    try:
        if sub_text:
            try:
                sub = Substructure.model_validate_json(sub_text)
                for pt in sub.pileTypes:
                    res = load_tests.pile_type_tests(sub.loadTests, pt, float(ep_mpa))
                    for item in res.get("results") or []:
                        project_results.append({"pileType": pt.id, **item})
                    notes.extend(res.get("notes") or [])
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Saved load tests skipped: {_first_line(exc)}")

        calc_res: dict[str, Any] | None = None
        if curve_text and curve_text.strip():
            pts: list[list[float]] = []
            for tok in curve_text.replace(";", ",").split(","):
                tok = tok.strip()
                if not tok:
                    continue
                sep = ":" if ":" in tok else " "
                parts = [p for p in tok.split(sep) if p.strip()]
                if len(parts) >= 2:
                    pts.append([float(parts[0]), float(parts[1])])
            if len(pts) >= 2:
                d_m = float(diameter_mm) / 1000.0
                area = math.pi * d_m**2 / 4.0
                c_pts = load_tests.curve(pts)
                dav = load_tests.davisson(c_pts, d_m, float(length_m), area, float(ep_mpa))
                bh = load_tests.butler_hoy(c_pts)
                br = load_tests.brinch_hansen(c_pts)
                mock_type = type(
                    "_TmpPile",
                    (),
                    {
                        "id": "Calculator",
                        "kind": "driven",
                        "diameter": float(diameter_mm),
                        "length": float(length_m) * 1000.0,
                        "shape": "round",
                    },
                )()
                mock_test = PileLoadTest(
                    id="Custom",
                    pileType="Calculator",
                    kind="compression",
                    stage="initial",
                    points=pts,
                )
                comp = load_tests.compression(mock_test, mock_type, float(ep_mpa))
                calc_res = {
                    "points": len(pts),
                    "safeKn": comp.get("safe"),
                    "davissonKn": round(dav, 1) if dav is not None else None,
                    "butlerHoyKn": round(bh, 1) if bh is not None else None,
                    "brinchHansenKn": round(br, 1) if br is not None else None,
                    "note": comp.get("note", ""),
                }
        return _finite(
            {
                "projectTests": project_results,
                "calculator": calc_res,
                "notes": notes,
                "problems": [],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "projectTests": [],
            "calculator": None,
            "notes": notes,
            "problems": [_first_line(error)],
        }


def substructure_pile_detailing(
    project_root: str,
    *,
    kind: str = "bored",
    diameter_mm: float = 600.0,
    fc_mpa: float = 28.0,
    fy_mpa: float = 420.0,
    placement: str = "tremie",
) -> dict[str, Any]:
    """Pile reinforcement detailing checks, minimum concrete strength, and tremie/dry mix guidance."""
    from saengine.library.substructure import Substructure
    from saengine.substructure import pile_detailing

    root = Path(project_root)
    sub_text = _read_text(root / "09 Substructure/substructure.json")
    checks_out: list[dict[str, Any]] = []
    notes: list[str] = []
    try:
        min_fc, fc_note = pile_detailing.least_fc(kind)
        mix_note = pile_detailing.recommended_mix(float(diameter_mm), placement)
        guid = pile_detailing.guidance_note(float(diameter_mm))
        if fc_note:
            notes.append(fc_note)
        if mix_note:
            notes.append(mix_note)
        if guid:
            notes.append(guid)

        if sub_text:
            try:
                sub = Substructure.model_validate_json(sub_text)
                for pt in sub.pileTypes:
                    chks, pt_notes = pile_detailing.detailing_checks(
                        pt, float(fc_mpa), float(fy_mpa)
                    )
                    for c in chks:
                        checks_out.append({"pileType": pt.id, **c})
                    notes.extend(pt_notes)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Saved pile types skipped: {_first_line(exc)}")

        return _finite(
            {
                "kind": kind,
                "minFcMpa": round(min_fc, 1),
                "recommendedMix": mix_note or "–",
                "guidance": guid or "–",
                "checks": checks_out,
                "notes": notes,
                "problems": [],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {"checks": [], "notes": notes, "problems": [_first_line(error)]}


def substructure_basement_loads(project_root: str) -> dict[str, Any]:
    """At-rest earth and water pressures (Load Case H) acting on basement walls."""
    from saengine.library.bim import BuildingModel
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import ProjectSettings, default_project_settings
    from saengine.library.substructure import Substructure
    from saengine.substructure import basement_loads

    root = Path(project_root)
    bim_text = _read_text(root / "06 BIM/bim.json")
    obj_text = _read_text(root / "04 Objects/objects.json")
    if not bim_text or not obj_text:
        return {
            "walls": [],
            "notes": [
                "06 BIM/bim.json and 04 Objects/objects.json are needed to detect basement walls."
            ],
            "problems": [],
        }
    set_text = _read_text(root / "02 Project Settings/project-settings.json")
    sub_text = _read_text(root / "09 Substructure/substructure.json")
    soil_text = _read_text(root / "01 Soil Report/soil-report.json")
    try:
        building = BuildingModel.model_validate_json(bim_text)
        objects = ObjectLibrary.model_validate_json(obj_text)
        settings = (
            ProjectSettings.model_validate_json(set_text)
            if set_text
            else default_project_settings()
        )
        sub = Substructure.model_validate_json(sub_text) if sub_text else None
        walls_by_id = {
            e.id: e for e in building.elements if hasattr(e, "bottom") and hasattr(e, "top")
        }
        pressures, notes = basement_loads.basement_pressures(
            building, objects, settings, sub, soil_text
        )
        rows = []
        for wp in pressures:
            w = walls_by_id.get(wp.wall)
            top = float(getattr(w, "top", 0.0))
            bot = float(getattr(w, "bottom", -3000.0))
            mid = (top + bot) / 2.0
            rows.append(
                {
                    "wall": wp.wall,
                    "source": wp.source,
                    "direction": [round(float(v), 3) for v in wp.direction],
                    "pTopKpa": round(float(wp.pressure(top)), 2),
                    "pMidKpa": round(float(wp.pressure(mid)), 2),
                    "pBotKpa": round(float(wp.pressure(bot)), 2),
                }
            )
        if not rows and not notes:
            notes.append("No basement walls found below the finished ground level.")
        return _finite({"walls": rows, "notes": notes, "problems": []})
    except Exception as error:  # noqa: BLE001
        return {"walls": [], "notes": [], "problems": [_first_line(error)]}


def substructure_embedded_wall(
    project_root: str,
    *,
    height_m: float = 5.0,
    kind: str = "cantilever",
    support: str = "free",
    prop_depth_m: float = 1.5,
    surcharge_kpa: float = 10.0,
    water_table_m: float | None = None,
) -> dict[str, Any]:
    """Embedded excavation wall embedment, bending moment, prop force, uplift and seepage checks."""
    from saengine.substructure import earth_pressure as sub_ep
    from saengine.substructure import embedded_wall, excavation, piles

    root = Path(project_root)
    soil_text = _read_text(root / "01 Soil Report/soil-report.json")
    try:
        profiles = piles.profiles_of(soil_text)[0] if soil_text else []
        wt = float(water_table_m) if water_table_m is not None and water_table_m >= 0 else None
        if profiles:
            soil_col = sub_ep.soil_column(
                profiles,
                float(profiles[0].borehole.x),
                float(profiles[0].borehole.y),
                water_table=wt,
                surcharge=float(surcharge_kpa),
            )
        else:
            soil_col = sub_ep.soil_column(
                [],
                0.0,
                0.0,
                water_table=wt,
                surcharge=float(surcharge_kpa),
                override={"phi": 30.0, "gamma": 18.0, "c": 0.0},
            )
        res = embedded_wall.design_wall(
            soil_col,
            float(height_m),
            kind,
            support,
            float(prop_depth_m) if kind == "propped" else None,
            float(surcharge_kpa),
        )
        embed = float(res.get("d") or 0.0)
        uplift = excavation.base_uplift(soil_col, float(height_m), 1.5)
        seepage = (
            excavation.seepage_gradient(soil_col, float(height_m), embed, 2.0)
            if embed > 0
            else None
        )
        return _finite(
            {
                "source": soil_col.source,
                "wall": res,
                "uplift": uplift,
                "seepage": seepage,
                "notes": list(res.get("notes") or []),
                "problems": []
                if res.get("ok", True)
                else [str(res.get("reason") or "Embedded wall equilibrium failed.")],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "wall": {},
            "uplift": None,
            "seepage": None,
            "notes": [],
            "problems": [_first_line(error)],
        }


def substructure_ground_slab(
    project_root: str,
    *,
    thickness_mm: float = 150.0,
    fc_mpa: float = 25.0,
    subgrade_kn_m3: float = 30000.0,
    point_load_kn: float = 50.0,
    contact_side_mm: float = 150.0,
    fy_mpa: float = 420.0,
) -> dict[str, Any]:
    """Ground-bearing slab Westergaard flexural stresses, punching shear, and shrinkage check."""
    from saengine.library.materials import concrete_modulus
    from saengine.library.substructure import GroundSlab
    from saengine.substructure import ground_slab

    try:
        fc = max(5.0, float(fc_mpa))
        e_mpa = concrete_modulus(fc)
        slab = GroundSlab(
            id="Calculator",
            outline=[[0.0, 0.0], [5000.0, 0.0], [5000.0, 5000.0], [0.0, 5000.0]],
            thickness=float(thickness_mm),
            material="C25",
            subgradeModulus=float(subgrade_kn_m3),
            pointLoad=float(point_load_kn),
            contactSide=float(contact_side_mm),
        )
        checks = ground_slab.ground_slab_checks(
            slab, fc, e_mpa, 0.2, float(subgrade_kn_m3), float(fy_mpa)
        )
        l_rel = ground_slab.relative_stiffness(
            e_mpa, float(thickness_mm), 0.2, float(subgrade_kn_m3) * 1e-6
        )
        fr = ground_slab.modulus_of_rupture(fc)
        return _finite(
            {
                "eMpa": round(e_mpa, 1),
                "frMpa": round(fr, 2),
                "relativeStiffnessMm": round(l_rel, 1),
                "checks": checks,
                "notes": [],
                "problems": [],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {"checks": [], "notes": [], "problems": [_first_line(error)]}


def substructure_limit_state(project_root: str) -> dict[str, Any]:
    """Inspect active code pack geotechnical limit-state partial factors and correlation factors."""
    from saengine.report.clauses import in_force
    from saengine.substructure import (
        limit_state_footings,
        limit_state_piles,
        limit_state_retaining,
    )
    from saengine.substructure import (
        limit_state_geotechnics as lsg,
    )

    try:
        with in_force(project_root) as pack_problems:
            rules = lsg.rules()
            if rules is None:
                return {
                    "covered": False,
                    "designApproach": None,
                    "combinations": [],
                    "correlations": [],
                    "selected": {},
                    "notes": [
                        "The active code pack designs foundations by working/allowable stresses (no geotechnicalMethods limit-state table)."
                    ],
                    "problems": list(pack_problems),
                }
            combos = [
                c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c)
                for c in lsg.combinations()
            ]
            corrs = [
                {
                    "n": n,
                    "xiBase": lsg.correlation_factors(n, load_tests=False)[0],
                    "xiLoadTest": lsg.correlation_factors(n, load_tests=True)[0],
                }
                for n in (1, 2, 3, 4, 5, 7, 10)
            ]
            return _finite(
                {
                    "covered": True,
                    "designApproach": getattr(rules, "designApproach", None),
                    "combinations": combos,
                    "correlations": corrs,
                    "selected": {
                        "footings": bool(limit_state_footings.selected()),
                        "piles": bool(limit_state_piles.selected()),
                        "retaining": bool(limit_state_retaining.selected()),
                    },
                    "notes": [],
                    "problems": list(pack_problems),
                }
            )
    except Exception as error:  # noqa: BLE001
        return {
            "covered": False,
            "combinations": [],
            "correlations": [],
            "problems": [_first_line(error)],
        }


# ────────────────────────────────────────── BOQ ──────────────────────────────────────────


def boq_summary(project_root: str) -> dict[str, Any]:
    """Summarize saved BOQ quantities, cost lines, embodied carbon lines, and estimating conventions."""
    from saengine.boq import costing, quantities

    root = Path(project_root)
    boq_text = _read_text(root / "10 BOQ/boq.json")
    if not boq_text:
        return {
            "hasBoq": False,
            "items": [],
            "costing": None,
            "conventions": quantities.materials_conventions(),
            "notes": ["10 BOQ/boq.json not found. Run Measure / Update from Building Model first."],
            "problems": [],
        }
    rates_text = _read_text(root / "10 BOQ/rates.json")
    carbon_text = _read_text(root / "10 BOQ/carbon-factors.json")
    try:
        bill = json.loads(boq_text)
        cost_res = costing.cost_texts(boq_text, rates_text, carbon_text)
        return _finite(
            {
                "hasBoq": True,
                "items": list(bill.get("items") or []),
                "costing": cost_res.get("costing"),
                "sampleRates": bool(cost_res.get("sampleRates")),
                "conventions": quantities.materials_conventions(),
                "notes": list(bill.get("notes") or []),
                "problems": [],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {"hasBoq": False, "items": [], "costing": None, "problems": [_first_line(error)]}


def boq_bar_schedule(project_root: str) -> dict[str, Any]:
    """Compute the drawing-derived bar bending schedule summary and reconciliation notes."""
    from saengine.boq import schedule

    root = Path(project_root)
    texts = {
        "bim": _read_text(root / "06 BIM/bim.json"),
        "objects": _read_text(root / "04 Objects/objects.json"),
        "materials": _read_text(root / "03 Materials/materials.json"),
        "settings": _read_text(root / "02 Project Settings/project-settings.json"),
        "substructure": _read_text(root / "09 Substructure/substructure.json"),
    }
    try:
        sched, notes = schedule.schedule_of(texts, str(root))
        if sched is None:
            return {"hasSchedule": False, "bars": [], "marks": [], "notes": notes, "problems": []}
        bars_by_dia: dict[float, float] = {}
        marks_out: list[dict[str, Any]] = []
        for mark in getattr(sched, "marks", []):
            d = float(getattr(mark, "dia", 0.0))
            mass = float(getattr(mark, "mass", 0.0))
            bars_by_dia[d] = bars_by_dia.get(d, 0.0) + mass
            marks_out.append(
                {
                    "mark": getattr(mark, "mark", ""),
                    "member": getattr(mark, "member", ""),
                    "kind": getattr(mark, "kind", ""),
                    "diaMm": d,
                    "count": getattr(mark, "count", 0),
                    "cutLengthMm": getattr(mark, "length", 0.0),
                    "massKg": round(mass, 2),
                }
            )
        dia_rows = [{"diaMm": d, "totalKg": round(m, 2)} for d, m in sorted(bars_by_dia.items())]
        return _finite(
            {
                "hasSchedule": True,
                "takenNote": schedule.taken_note(sched),
                "byDiameter": dia_rows,
                "marks": marks_out[:500],
                "markCount": len(marks_out),
                "notes": notes,
                "problems": [],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {
            "hasSchedule": False,
            "byDiameter": [],
            "marks": [],
            "notes": [],
            "problems": [_first_line(error)],
        }


def boq_schedule_summary(project_root: str) -> dict[str, Any]:
    """Read `10 BOQ/construction-schedule.json` and evaluate CPM early/late dates and critical path."""
    from saengine.boq import construction_schedule as cs

    root = Path(project_root)
    sched_text = _read_text(root / "10 BOQ/construction-schedule.json")
    if not sched_text:
        return {
            "hasSchedule": False,
            "schedule": None,
            "notes": [
                "10 BOQ/construction-schedule.json not found. Run Generate 4D Programme first."
            ],
            "problems": [],
        }
    try:
        res = cs.reschedule_text(sched_text)
        return _finite(
            {"hasSchedule": "schedule" in res, **res, "problems": list(res.get("problems") or [])}
        )
    except Exception as error:  # noqa: BLE001
        return {"hasSchedule": False, "schedule": None, "problems": [_first_line(error)]}


def boq_arch_takeoff(project_root: str) -> dict[str, Any]:
    """Measure architectural masonry, plaster, finishes, doors and windows quantities."""
    from saengine.boq import architecture as boq_arch
    from saengine.boq import costing, quantities
    from saengine.library import architecture as arch_lib

    root = Path(project_root)
    bim_text = _read_text(root / "06 BIM/bim.json")
    obj_text = _read_text(root / "04 Objects/objects.json")
    mat_text = _read_text(root / "03 Materials/materials.json")
    arch_text = _read_text(root / arch_lib.ARCHITECTURE_FILE)
    if not arch_text:
        return {
            "hasContent": False,
            "items": [],
            "notes": ["05 Floor Plan/architecture.json not found."],
            "problems": [],
        }
    try:
        arch = arch_lib.parse(arch_text)
        if not boq_arch.has_content(arch):
            return {
                "hasContent": False,
                "items": [],
                "notes": ["Architecture has no walls, rooms, doors or windows yet."],
                "problems": [],
            }
        if not bim_text or not obj_text or not mat_text:
            return {
                "hasContent": True,
                "items": [],
                "notes": [
                    "Generate 06 BIM first to measure architectural takeoff against structural openings."
                ],
                "problems": [],
            }
        res = quantities.compute_boq(
            bim_text,
            obj_text,
            mat_text,
            substructure_text=_read_text(root / "09 Substructure/substructure.json"),
            settings_text=_read_text(root / "02 Project Settings/project-settings.json"),
            project_root=str(root),
            architecture_text=arch_text,
        )
        if not res.get("text"):
            return {
                "hasContent": True,
                "items": [],
                "notes": [],
                "problems": list(res.get("problems") or []),
            }
        bill = json.loads(res["text"])
        arch_items = [
            it
            for it in bill.get("items") or []
            if it.get("group") in ("masonry", "finishes", "furniture")
            or it.get("kind") in costing.ARCHITECTURE_KINDS
        ]
        return _finite(
            {
                "hasContent": True,
                "items": arch_items,
                "notes": list(res.get("notes") or []),
                "problems": [],
            }
        )
    except Exception as error:  # noqa: BLE001
        return {"hasContent": False, "items": [], "notes": [], "problems": [_first_line(error)]}


def boq_precast_schedule(project_root: str) -> dict[str, Any]:
    """Precast piece schedule (count, dimensions, concrete, weight, bars, inserts, mould area)."""
    from saengine.boq.precast import piece_schedule
    from saengine.design.precast import pieces_of
    from saengine.library.bim import BuildingModel
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    root = Path(project_root)
    bim_text = _read_text(root / "06 BIM/bim.json")
    obj_text = _read_text(root / "04 Objects/objects.json")
    mat_text = _read_text(root / "03 Materials/materials.json")
    if not bim_text or not obj_text:
        return {
            "items": [],
            "totals": {},
            "notes": ["06 BIM/bim.json and 04 Objects/objects.json are required."],
            "problems": [],
        }
    try:
        building = BuildingModel.model_validate_json(bim_text)
        objects = ObjectLibrary.model_validate_json(obj_text)
        materials = MaterialLibrary.model_validate_json(mat_text) if mat_text else None
        types = {o.id: o for o in objects.objects}
        mat_map = {m.id: m for m in materials.materials} if materials else None
        pieces = pieces_of(building, objects)
        sched = piece_schedule(pieces, types, mat_map)
        notes = (
            []
            if sched.get("items")
            else ["No precast object types or precast members found in 06 BIM."]
        )
        return _finite({**sched, "notes": notes, "problems": []})
    except Exception as error:  # noqa: BLE001
        return {"items": [], "totals": {}, "notes": [], "problems": [_first_line(error)]}


def boq_takeoff_summary(project_root: str) -> dict[str, Any]:
    """Read and summarize `10 BOQ/takeoff.json` 2D PDF quantity takeoff items."""
    from saengine.boq import takeoff

    root = Path(project_root)
    text = _read_text(root / "10 BOQ/takeoff.json")
    if not text:
        return {
            "hasTakeoff": False,
            "items": [],
            "notes": ["10 BOQ/takeoff.json not found. Use 2D PDF Takeoff in Office Tools first."],
            "problems": [],
        }
    try:
        res = takeoff.summary(text)
        return _finite({"hasTakeoff": True, **res, "problems": list(res.get("problems") or [])})
    except Exception as error:  # noqa: BLE001
        return {"hasTakeoff": False, "items": [], "problems": [_first_line(error)]}
