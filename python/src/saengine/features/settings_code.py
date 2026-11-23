"""Project Settings - Code Pack & General tab: code packs, design basis, location, localisation, paths, and licensing."""

from __future__ import annotations

import math
import platform
import sys
from typing import Any

from saengine import __version__
from saengine import units as units_lib
from saengine.codes import catalogue, conformance, registry, trust
from saengine.codes import context as code_context
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
from saengine.features.settings_common import (
    active_pack,
    export_file,
    json_dumps_clean,
    load_settings,
    safe_table,
)
from saengine.gis import towns as gis_towns
from saengine.gis.crs import haversine_km
from saengine.library.settings import code_basis, settings_for_pack
from saengine.report.clauses import in_force


@feature(
    "settings.designCodeSet",
    "Design Code Set",
    part="settings",
    fields=[
        text("targetPackId", "Target code pack ID (blank = active)", ""),
    ],
    requires_project=False,
)
def design_code_set(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List available design code packs and preview switching the project to a target pack."""
    st = load_settings(ctx)
    reg = registry.default_registry()
    infos = [p for p in reg.list_packs(ctx.root, "designCode") if p.effective]
    target_id = values["targetPackId"].strip() or st.codePack

    with in_force(ctx.root, st):
        active = active_pack(ctx, st)
        basis = code_basis(st)
        try:
            preview = settings_for_pack(st, target_id)
        except registry.CodePackError as exc:
            raise FeatureInputError(f"Code pack '{target_id}' is unavailable: {exc}") from exc

    rows = [
        {
            "id": p.id,
            "name": p.name,
            "country": p.country or "-",
            "version": p.version,
            "scope": p.scope,
            "usable": p.usable,
            "active": p.id == active.id,
        }
        for p in infos
    ]
    return result(
        summary={
            "activePack": active.id,
            "targetPack": target_id,
            "availablePackCount": len(rows),
            "targetLocation": preview.site.location,
            "targetSystem": preview.seismic.system,
            "combinationCount": len(preview.combinations),
        },
        tables=[
            table(
                "Installed design code packs",
                [
                    ("id", "Pack ID"),
                    ("name", "Name"),
                    ("country", "Country"),
                    ("version", "Version"),
                    ("scope", "Scope"),
                    ("usable", "Usable"),
                    ("active", "Active"),
                ],
                rows,
            )
        ],
        notes=[
            f"Active basis: general = {basis.general}; concrete = {basis.concrete}; steel = {basis.steel}.",
            "Target preview resolves location, site class, seismic system, wind exposure, and combinations from the pack.",
        ],
    )


@feature(
    "settings.codeEdition",
    "Code Edition",
    part="settings",
    fields=[
        text("packId", "Code pack ID (blank = active)", ""),
    ],
    requires_project=False,
)
def code_edition(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect the active code pack's edition, inheritance chain, verification, and conformance."""
    st = load_settings(ctx)
    pack_id = values["packId"].strip() or st.codePack
    with in_force(ctx.root, st):
        try:
            pack = registry.load(pack_id, ctx.root)
        except registry.CodePackError as exc:
            raise FeatureInputError(f"Cannot load code pack '{pack_id}': {exc}") from exc
        findings = conformance.check_pack(pack)
    err_count = sum(1 for f in findings if f.level == "error")
    warn_count = sum(1 for f in findings if f.level == "warning")
    chain_rows = [
        {
            "depth": idx,
            "id": f.id,
            "scope": f.scope,
            "version": f.manifest.version if f.manifest else "-",
            "edition": (f.manifest.edition or f.manifest.name) if f.manifest else "-",
        }
        for idx, f in enumerate(pack._chain)
    ]
    return result(
        summary={
            "packId": pack.id,
            "edition": pack.edition or pack.name,
            "version": pack.info.version,
            "coveredTables": len(pack.tables()),
            "conformanceErrors": err_count,
            "conformanceWarnings": warn_count,
        },
        tables=[
            table(
                "Inheritance chain",
                [
                    ("depth", "Order"),
                    ("id", "Pack ID"),
                    ("scope", "Scope"),
                    ("version", "Version"),
                    ("edition", "Edition"),
                ],
                chain_rows,
            )
        ],
        notes=[f"Verification status: {pack.verification.status} ({pack.verification.message})."],
    )


@feature(
    "settings.designApproach",
    "Design Approach",
    part="settings",
    fields=[
        select(
            "approach",
            "Geotechnical design approach",
            [
                ("pack", "Use active code pack factors"),
                ("da1c1", "Design Approach 1 - Combination 1 (actions factored)"),
                ("da1c2", "Design Approach 1 - Combination 2 (soil factored)"),
                ("da2", "Design Approach 2 (actions & resistance factored)"),
                ("da3", "Design Approach 3 (structural actions & soil factored)"),
            ],
            "pack",
        ),
        number(
            "characteristicLoadKn", "Characteristic vertical load Vk", 900.0, unit="kN", min=0.0
        ),
        number(
            "characteristicBearingKpa",
            "Characteristic ultimate bearing qult",
            450.0,
            unit="kPa",
            min=1.0,
        ),
        number("footingAreaM2", "Footing plan area", 4.0, unit="m²", min=0.1),
    ],
    requires_project=False,
)
def design_approach(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate geotechnical partial factors and factored bearing check under the chosen approach."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ft = safe_table(pack, "foundations")
    approach = values["approach"]
    vk = values["characteristicLoadKn"]
    qult = values["characteristicBearingKpa"]
    area = values["footingAreaM2"]

    presets = {
        "da1c1": (1.35, 1.0, 1.0),
        "da1c2": (1.0, 1.25, 1.0),
        "da2": (1.35, 1.0, 1.4),
        "da3": (1.35, 1.25, 1.0),
    }
    if approach == "pack":
        shallow_tbl = getattr(ft, "shallow", None) if ft else None
        phi_bearing = (
            getattr(shallow_tbl, "bearingPhi", None) or getattr(ft, "sptSafety", 2.5) if ft else 2.5
        )
        gamma_g = 1.0
        gamma_m = 1.0
        gamma_r = (
            float(phi_bearing) if float(phi_bearing) >= 1.0 else 1.0 / max(float(phi_bearing), 0.1)
        )
    else:
        gamma_g, gamma_m, gamma_r = presets[approach]

    ved = vk * gamma_g
    q_design = qult / (gamma_m * gamma_r)
    rd = q_design * area
    util = ved / rd if rd > 0 else float("inf")
    rows = [
        {"parameter": "Action partial factor γG", "value": gamma_g, "unit": "-"},
        {"parameter": "Material partial factor γM", "value": gamma_m, "unit": "-"},
        {"parameter": "Resistance factor γR", "value": gamma_r, "unit": "-"},
        {"parameter": "Design vertical demand Vd", "value": ved, "unit": "kN"},
        {"parameter": "Design bearing resistance Rd", "value": rd, "unit": "kN"},
    ]
    return result(
        summary={
            "approach": approach,
            "designDemandKn": ved,
            "designResistanceKn": rd,
            "utilisation": util,
            "passing": util <= 1.0,
        },
        tables=[
            table(
                "Geotechnical design approach factors",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[f"Code pack in force: {code_context.code_name(pack)}. Utilisation = Vd / Rd."],
    )


@feature(
    "settings.nationalAnnex",
    "National Annex",
    part="settings",
    fields=[
        text("annexPackId", "National annex / child pack ID (blank = active)", ""),
    ],
    requires_project=False,
)
def national_annex(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect national annex / regional extension parameters and table ownership."""
    st = load_settings(ctx)
    target = values["annexPackId"].strip() or st.codePack
    with in_force(ctx.root, st):
        try:
            pack = registry.load(target, ctx.root)
        except registry.CodePackError as exc:
            raise FeatureInputError(f"Cannot load pack '{target}': {exc}") from exc
        key_tables = (
            "locations",
            "seismic",
            "wind",
            "combinations",
            "concrete",
            "steel",
            "foundations",
            "factors",
        )
        rows = []
        for tbl in key_tables:
            if pack.has(tbl):
                owner = pack.value_owner(tbl)
                rows.append(
                    {
                        "table": tbl,
                        "ownerPack": owner[0] if owner else pack.id,
                        "codeLabel": owner[1] if owner else (pack.edition or pack.name),
                        "overriddenLocally": (owner[0] == pack.id) if owner else True,
                    }
                )
    return result(
        summary={
            "packId": pack.id,
            "country": pack.info.country or "-",
            "extends": pack.info.extends or "none",
            "units": pack.info.units or "SI",
            "tableCount": len(rows),
        },
        tables=[
            table(
                "Table ownership across national annex / inheritance",
                [
                    ("table", "Table"),
                    ("ownerPack", "Providing pack"),
                    ("codeLabel", "Code basis"),
                    ("overriddenLocally", "Defined in leaf"),
                ],
                rows,
            )
        ],
        notes=["Shows which pack in the inheritance chain supplies each engineering table."],
    )


@feature(
    "settings.designWorkingLife",
    "Design Working Life",
    part="settings",
    fields=[
        number("workingLifeYears", "Design working life T", 50.0, unit="yr", min=1.0, max=200.0),
        number("returnPeriodYears", "Reference hazard return period Tr", 475.0, unit="yr", min=1.0),
    ],
    requires_project=False,
)
def design_working_life(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate lifetime exceedance probability and durability structural class impact of design life."""
    t_life = values["workingLifeYears"]
    t_ret = values["returnPeriodYears"]
    annual_p = 1.0 - math.exp(-1.0 / t_ret)
    life_p = 1.0 - (1.0 - annual_p) ** t_life

    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        occ_tbl = safe_table(pack, "occupancyCategories")
        cat = occ_tbl.categories.get(st.occupancy.category) if occ_tbl else None
        cm = safe_table(pack, "concreteMethods")
        life_bump = getattr(getattr(cm, "cover", None), "longLifeIncrease", 2) if cm else 2

    s_adjust = int(life_bump) if t_life >= 100.0 else 0
    rows = [
        {"metric": "Design working life", "value": t_life, "unit": "yr"},
        {"metric": "Reference return period", "value": t_ret, "unit": "yr"},
        {"metric": "Annual exceedance probability", "value": annual_p * 100.0, "unit": "%"},
        {"metric": "Lifetime exceedance probability", "value": life_p * 100.0, "unit": "%"},
        {"metric": "Durability structural class step", "value": float(s_adjust), "unit": "class"},
    ]
    return result(
        summary={
            "workingLifeYears": t_life,
            "annualExceedancePct": annual_p * 100.0,
            "lifetimeExceedancePct": life_p * 100.0,
            "seismicImportance": float(cat.seismicImportance) if cat else 1.0,
            "structuralClassIncrease": s_adjust,
        },
        tables=[
            table(
                "Design working life parameters",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Poisson exceedance model: P_life = 1 - (1 - P_annual)^T_life."],
    )


@feature(
    "settings.consequenceClass",
    "Consequence Class",
    part="settings",
    fields=[
        select(
            "consequenceClass",
            "Consequence class",
            [
                ("CC1", "CC1 - Low consequence for loss of human life"),
                ("CC2", "CC2 - Medium consequence (normal buildings)"),
                ("CC3", "CC3 - High consequence (major public / essential)"),
            ],
            "CC2",
        ),
    ],
    requires_project=False,
)
def consequence_class(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map consequence class to target reliability index, action multiplier KFI, and supervision level."""
    cc = values["consequenceClass"]
    mapping = {
        "CC1": ("RC1", 3.3, 0.9, "Self-checking (DSL1)"),
        "CC2": ("RC2", 3.8, 1.0, "Normal independent checking (DSL2)"),
        "CC3": ("RC3", 4.3, 1.1, "Extended third-party review (DSL3)"),
    }
    rc, beta_50, kfi, supervision = mapping[cc]
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        occ_tbl = safe_table(pack, "occupancyCategories")
        cat = occ_tbl.categories.get(st.occupancy.category) if occ_tbl else None
    rows = [
        {
            "consequenceClass": cc,
            "reliabilityClass": rc,
            "beta50": beta_50,
            "kfiFactor": kfi,
            "projectCategory": st.occupancy.category,
            "supervision": supervision,
        }
    ]
    return result(
        summary={
            "consequenceClass": cc,
            "reliabilityClass": rc,
            "targetBeta50": beta_50,
            "kfiFactor": kfi,
            "occupancySeismicImportance": float(cat.seismicImportance) if cat else 1.0,
        },
        tables=[
            table(
                "Consequence & reliability assignment",
                [
                    ("consequenceClass", "CC"),
                    ("reliabilityClass", "RC"),
                    ("beta50", "β (50 yr)"),
                    ("kfiFactor", "K_FI"),
                    ("projectCategory", "Occupancy Cat"),
                    ("supervision", "Supervision"),
                ],
                rows,
            )
        ],
        notes=[
            "Target reliability indices β and action factor K_FI follow standard limit-state reliability classes."
        ],
    )


@feature(
    "settings.exposureConditions",
    "Exposure Conditions",
    part="settings",
    fields=[
        select(
            "exposure",
            "Primary exposure condition",
            [
                ("XC1", "Dry / permanently wet interior"),
                ("XC3", "Moderate humidity / sheltered external"),
                ("XC4", "Cyclic wet and dry external"),
                ("XD1", "Moderate humidity with chlorides"),
                ("XS1", "Airborne marine salt (coastal)"),
                ("XS3", "Tidal, splash and spray zones"),
            ],
            "XC3",
        ),
        number("barDiameterMm", "Main bar diameter", 20.0, unit="mm", min=6.0, max=50.0),
        number("fckMpa", "Concrete cylinder strength f'c", 28.0, unit="MPa", min=15.0, max=100.0),
        number("aggregateMm", "Max aggregate size", 20.0, unit="mm", min=10.0, max=50.0),
    ],
    requires_project=False,
)
def exposure_conditions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute nominal concrete cover and durability requirements from code pack or durability classes."""
    exp = values["exposure"]
    bar = values["barDiameterMm"]
    fck = values["fckMpa"]
    agg = values["aggregateMm"]
    st = load_settings(ctx)

    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        cm = safe_table(pack, "concreteMethods")
        if cm is not None and getattr(cm, "cover", None) is not None:
            from saengine.design.bar_rules import nominal_cover

            cov = nominal_cover([exp], bar, fck, aggregate=agg)
            cmin_b, cmin_dur, cnom = cov["cminB"], cov["cminDur"], cov["cnom"]
            source = "Active code pack concreteMethods.cover"
        else:
            conc = safe_table(pack, "concrete")
            dur_map = {"XC1": 15.0, "XC3": 25.0, "XC4": 30.0, "XD1": 35.0, "XS1": 40.0, "XS3": 50.0}
            cmin_b = bar + (5.0 if agg > 32.0 else 0.0)
            cmin_dur = dur_map[exp]
            min_cov = (
                float(getattr(conc, "cover", {}).get("beam", 25.0))
                if conc and isinstance(getattr(conc, "cover", None), dict)
                else 25.0
            )
            cnom = max(cmin_b, cmin_dur, min_cov) + 10.0
            source = "Exposure durability envelope with 10 mm deviation allowance"

    rows = [
        {"term": "Bond minimum cmin,b", "mm": cmin_b},
        {"term": "Durability minimum cmin,dur", "mm": cmin_dur},
        {"term": "Nominal cover cnom", "mm": cnom},
    ]
    return result(
        summary={
            "exposure": exp,
            "cminBondMm": cmin_b,
            "cminDurabilityMm": cmin_dur,
            "nominalCoverMm": cnom,
        },
        tables=[table("Cover breakdown", [("term", "Component"), ("mm", "Cover", "mm")], rows)],
        notes=[f"Source: {source} (pack: {code_context.code_name(pack)})."],
    )


@feature(
    "settings.siteLocation",
    "Site Location",
    part="settings",
    fields=[
        number("latitudeDeg", "Site latitude", 23.8103, unit="°", min=-90.0, max=90.0),
        number("longitudeDeg", "Site longitude", 90.4125, unit="°", min=-180.0, max=180.0),
        number("elevationM", "Site elevation above MSL", 12.0, unit="m", min=-100.0, max=6000.0),
    ],
    requires_project=False,
)
def site_location(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Locate the nearest code hazard station to site coordinates and report zone/wind parameters."""
    lat = values["latitudeDeg"]
    lon = values["longitudeDeg"]
    elev = values["elevationM"]
    st = load_settings(ctx)

    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        town_list = gis_towns.towns()
        if town_list:
            nearest_town, dist_km = gis_towns.nearest(lat, lon)
            town_name = nearest_town.name
            z_val = nearest_town.z
            v_val = nearest_town.wind_speed
        else:
            locs = safe_table(pack, "locations")
            loc_row = locs.locations.get(st.site.location) if locs else None
            town_name = loc_row.name if loc_row else st.site.location
            dist_km = 0.0
            z_val = st.site.zoneCoefficient
            v_val = loc_row.windSpeed if loc_row else st.site.windSpeed

        top_towns = sorted(
            (
                {
                    "town": t.name,
                    "distanceKm": haversine_km(lat, lon, t.latitude, t.longitude),
                    "z": t.z if t.z is not None else "-",
                    "windMPerS": t.wind_speed if t.wind_speed is not None else "-",
                }
                for t in town_list
            ),
            key=lambda r: float(r["distanceKm"]),
        )[:5]

    return result(
        summary={
            "nearestStation": town_name,
            "distanceKm": dist_km,
            "elevationM": elev,
            "zCoefficient": float(z_val) if z_val is not None else 0.0,
            "windSpeedMPerS": float(v_val) if v_val is not None else 0.0,
        },
        tables=[
            table(
                "Nearest hazard stations",
                [
                    ("town", "Station"),
                    ("distanceKm", "Distance", "km"),
                    ("z", "Z"),
                    ("windMPerS", "Wind V", "m/s"),
                ],
                top_towns
                or [
                    {
                        "town": town_name,
                        "distanceKm": 0.0,
                        "z": z_val or "-",
                        "windMPerS": v_val or "-",
                    }
                ],
            )
        ],
        notes=[
            "Great-circle distance computed via WGS-84 Haversine formula against active code pack locations."
        ],
    )


@feature(
    "settings.revisionControl",
    "Revision Control",
    part="settings",
    fields=[
        select(
            "scheme",
            "Revision scheme",
            [
                ("numeric", "Numeric (0, 1, 2, ...)"),
                ("alpha", "Alphabetic (A, B, C, ...)"),
                ("prelim", "Preliminary (P1, P2, ...)"),
            ],
            "numeric",
        ),
        text("newDescription", "Next revision description", "Issued for structural coordination"),
    ],
    requires_project=False,
)
def revision_control(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review drawing revision history and generate the next revision sequence identifier."""
    st = load_settings(ctx)
    revs = st.drawings.revisions
    scheme = values["scheme"]
    if revs:
        last = revs[-1].code
        if scheme == "numeric" and last.isdigit():
            nxt = str(int(last) + 1)
        elif scheme == "alpha" and len(last) == 1 and last.isalpha():
            nxt = chr(ord(last.upper()) + 1)
        else:
            nxt = f"P{len(revs) + 1}" if scheme == "prelim" else str(len(revs))
    else:
        nxt = {"numeric": "0", "alpha": "A", "prelim": "P1"}[scheme]

    rows = [
        {
            "code": r.code,
            "date": r.date or "-",
            "by": r.by or "-",
            "description": r.description or "-",
        }
        for r in revs
    ]
    rows.append(
        {
            "code": f"{nxt} (next)",
            "date": "pending",
            "by": st.drawings.drawnBy or "-",
            "description": values["newDescription"],
        }
    )
    return result(
        summary={
            "currentStatus": st.drawings.status,
            "existingRevisions": len(revs),
            "nextRevisionCode": nxt,
        },
        tables=[
            table(
                "Revision register",
                [("code", "Rev"), ("date", "Date"), ("by", "By"), ("description", "Description")],
                rows,
            )
        ],
        notes=[
            "Revision workflow tracks oldest-first entries from project settings drawings.revisions."
        ],
    )


@feature(
    "settings.languagePack",
    "Language Pack",
    part="settings",
    fields=[
        select(
            "preferred", "Preferred report language", [("en", "English"), ("bn", "Bangla")], "en"
        ),
    ],
    requires_project=False,
)
def language_pack(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List installed language packs and verify active project language configuration."""
    st = load_settings(ctx)
    packs = [
        p for p in registry.default_registry().list_packs(ctx.root, "languagePack") if p.effective
    ]
    rows = [
        {"id": p.id, "name": p.name, "version": p.version, "scope": p.scope, "usable": p.usable}
        for p in packs
    ]
    return result(
        summary={
            "projectLanguage": st.project.language,
            "selectedLanguage": values["preferred"],
            "installedLanguagePacks": len(rows),
        },
        tables=[
            table(
                "Installed language packs",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("version", "Version"),
                    ("scope", "Scope"),
                    ("usable", "Usable"),
                ],
                rows
                or [
                    {
                        "id": "built-in",
                        "name": "Built-in English/Bangla",
                        "version": __version__,
                        "scope": "built-in",
                        "usable": True,
                    }
                ],
            )
        ],
        notes=[
            "Report and drawing text follows project.language while units and symbols remain invariant."
        ],
    )


@feature(
    "settings.regionalFormat",
    "Regional Format",
    part="settings",
    fields=[
        number("sampleValueKn", "Sample force value", 12345.67, unit="kN"),
        number("sampleStressMpa", "Sample stress value", 28.5, unit="MPa"),
        select(
            "dateStyle",
            "Date format convention",
            [("iso", "YYYY-MM-DD"), ("dmy", "DD/MM/YYYY"), ("mdy", "MM/DD/YYYY")],
            "iso",
        ),
    ],
    requires_project=False,
)
def regional_format(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview unit conversions and regional numeric/date formatting for reports and schedules."""
    st = load_settings(ctx)
    u = units_lib.units_of(st)
    f_val = values["sampleValueKn"]
    s_val = values["sampleStressMpa"]
    dates = {"iso": "2026-11-23", "dmy": "23/11/2026", "mdy": "11/23/2026"}
    rows = [
        {"quantity": "Force", "si": f"{f_val:,.2f} kN", "display": u.format(f_val, "kN")},
        {"quantity": "Stress", "si": f"{s_val:,.2f} MPa", "display": u.format(s_val, "MPa")},
        {"quantity": "Date", "si": "2026-11-23", "display": dates[values["dateStyle"]]},
    ]
    return result(
        summary={
            "unitSystem": st.units.system,
            "dateStyle": values["dateStyle"],
            "forceDisplay": u.format(f_val, "kN"),
        },
        tables=[
            table(
                "Formatting preview",
                [("quantity", "Quantity"), ("si", "SI stored"), ("display", "Formatted")],
                rows,
            )
        ],
        notes=[
            "Stored project values always remain SI; display formatting converts at output boundaries."
        ],
    )


@feature(
    "settings.contentFolders",
    "Content Folders",
    part="settings",
    fields=[],
    requires_project=False,
)
def content_folders(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect built-in, user, and project content folder paths and package counts."""
    reg = registry.default_registry()
    all_packs = reg.list_packs(ctx.root, "designCode")
    by_scope = {"built-in": 0, "user": 0, "project": 0}
    for p in all_packs:
        if p.scope in by_scope:
            by_scope[p.scope] += 1
    proj_dir = (
        str((ctx.root / registry.PROJECT_PACKS).resolve()) if ctx.root else "(no project open)"
    )
    rows = [
        {
            "scope": "Built-in packs",
            "path": str(registry.BUILTIN_DIR),
            "exists": registry.BUILTIN_DIR.is_dir(),
            "count": by_scope["built-in"],
        },
        {
            "scope": "User packs",
            "path": str(registry.user_packs_dir()),
            "exists": registry.user_packs_dir().is_dir(),
            "count": by_scope["user"],
        },
        {
            "scope": "Project packs",
            "path": proj_dir,
            "exists": bool(ctx.root and (ctx.root / registry.PROJECT_PACKS).is_dir()),
            "count": by_scope["project"],
        },
        {
            "scope": "User data / trust",
            "path": str(trust.user_data_dir()),
            "exists": trust.user_data_dir().is_dir(),
            "count": 0,
        },
    ]
    return result(
        summary={
            "builtinPacks": by_scope["built-in"],
            "userPacks": by_scope["user"],
            "projectPacks": by_scope["project"],
        },
        tables=[
            table(
                "Content directories",
                [
                    ("scope", "Scope"),
                    ("path", "Directory"),
                    ("exists", "Exists"),
                    ("count", "Packs"),
                ],
                rows,
            )
        ],
        notes=["Resolution precedence for matching pack IDs: project > user > built-in."],
    )


@feature(
    "settings.templateLocations",
    "Template Locations",
    part="settings",
    fields=[],
    requires_project=False,
)
def template_locations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Catalogue installed building templates and structure presets available to the workspace."""
    bld = catalogue.building_templates(ctx.root)
    stc = catalogue.structure_presets(ctx.root)
    rows = [
        {
            "kind": "Building template",
            "package": t["package"],
            "name": t["name"],
            "type": t["type"],
            "file": t["file"],
        }
        for t in bld["templates"]
    ] + [
        {
            "kind": "Structure preset",
            "package": p["package"],
            "name": p["name"],
            "type": "coded" if p.get("coded") else "parametric",
            "file": p["file"],
        }
        for p in stc["presets"]
    ]
    return result(
        summary={
            "buildingTemplateCount": len(bld["templates"]),
            "structurePresetCount": len(stc["presets"]),
            "problemCount": len(bld["problems"]) + len(stc["problems"]),
        },
        tables=[
            table(
                "Available templates & presets",
                [
                    ("kind", "Kind"),
                    ("package", "Package"),
                    ("name", "Name"),
                    ("type", "Type"),
                    ("file", "File"),
                ],
                rows,
            )
        ],
        notes=[
            "Discovered via active template catalogues across built-in and user template directories."
        ],
    )


@feature(
    "settings.featureLicences",
    "Feature Licences",
    part="settings",
    fields=[],
    requires_project=False,
)
def feature_licences(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit active open-source engine modules, design capabilities, and code pack availability."""
    from saengine import features as feat_reg

    feat_reg.load_all()
    packs = [
        p
        for p in registry.default_registry().list_packs(ctx.root, "designCode")
        if p.effective and p.usable
    ]
    modules = [
        ("fem", "Finite element & seismic/wind analysis"),
        ("design", "RC, steel, masonry, timber & composite design"),
        ("substructure", "Shallow, pile & retaining wall design"),
        ("soil", "Geotechnical borehole & liquefaction checks"),
        ("gis", "Site coordinate & hazard lookups"),
        ("special", "Bridges, moving loads, shells, offshore & towers"),
        ("drawings", "CAD detailing, bar schedules & automation"),
    ]
    rows = [{"module": m, "description": desc, "enabled": True} for m, desc in modules]
    return result(
        summary={
            "engineVersion": __version__,
            "registeredFeatures": len(feat_reg.REGISTRY),
            "usableCodePacks": len(packs),
            "allModulesActive": True,
        },
        tables=[
            table(
                "Engine capability audit",
                [("module", "Module"), ("description", "Scope"), ("enabled", "Enabled")],
                rows,
            )
        ],
        notes=["All open-source engine modules are active without seat restrictions."],
    )


@feature(
    "settings.offlineActivation",
    "Offline Activation",
    part="settings",
    fields=[
        checkbox("writeManifest", "Write manifest JSON to project exports", True),
    ],
    requires_project=False,
)
def offline_activation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate an offline environment & code-pack verification manifest."""
    st = load_settings(ctx)
    pack = active_pack(ctx, st)
    manifest = {
        "engineVersion": __version__,
        "pythonVersion": sys.version.split()[0],
        "platform": platform.platform(),
        "activeCodePack": pack.id,
        "packVersion": pack.info.version,
        "fingerprint": str(getattr(pack, "fingerprint", "")),
        "trustFile": str(trust.default_trust_file()),
    }
    out_path = None
    if values["writeManifest"] and ctx.root is not None:
        out_path = export_file(ctx, "offline-manifest.json", json_dumps_clean(manifest))
    rows = [{"key": k, "value": str(v)} for k, v in manifest.items()]
    return result(
        summary={
            "engineVersion": __version__,
            "activePack": pack.id,
            "manifestWritten": out_path is not None,
        },
        tables=[
            table("Offline verification manifest", [("key", "Field"), ("value", "Value")], rows)
        ],
        notes=[
            f"Manifest written to {out_path}"
            if out_path
            else "Open a project folder to save offline-manifest.json to exports."
        ],
    )
