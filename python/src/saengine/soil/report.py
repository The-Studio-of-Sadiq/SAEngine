"""The computed soil report: JSON-ready results for the editor, the footing design and Part 9.

Functions take the file texts (``01 Soil Report/soil-report.json`` and, optionally,
``02 Project Settings/project-settings.json``) and return plain dicts, ``{"problems": [...]}``
when the soil report cannot be read. :func:`soil_report` computes each borehole on its own:
one with a mistake, or one the computation fails on, is left out (``skipped``, with why in
``warnings`` and, for a failure, the traceback in ``details``) and the others are computed.

Lengths and depths are in mm (as in the file), pressures in kPa, ks in kN/m³, settlements in
mm.
"""

from __future__ import annotations

import json
import math
import traceback
from typing import Any

from pydantic import ValidationError

from saengine.library.settings import ProjectSettings, default_project_settings, derived
from saengine.library.soil import SoilReport, check, is_placeholder
from saengine.soil import (
    bearing,
    chemistry,
    code_data,
    investigation,
    lab,
    liquefaction,
    piles,
    site_class,
    special_soils,
)
from saengine.soil.profile import SPT_METHODS, Profile
from saengine.soil.settlement import permissible as settlement_permissible
from saengine.soil.settlement import permissible_text, rounded, settlement, soil_column

#: Boreholes within this distance of a footing all count; the lowest qa governs [mm].
NEARBY = 10_000.0


def messages(exc: ValidationError, data: Any, where: str = "Soil report") -> list[str]:
    """Validation errors with the borehole's id in place of its index."""
    out = []
    boreholes = data.get("boreholes") if isinstance(data, dict) else None
    for error in exc.errors():
        loc = list(error["loc"])
        if (
            len(loc) >= 2
            and loc[0] == "boreholes"
            and isinstance(loc[1], int)
            and isinstance(boreholes, list)
            and loc[1] < len(boreholes)
            and isinstance(boreholes[loc[1]], dict)
            and boreholes[loc[1]].get("id")
        ):
            loc = [str(boreholes[loc[1]]["id"]), *loc[2:]]
        for i, part in enumerate(loc):
            if isinstance(part, int):
                loc[i] = str(part + 1)  # 1-based for people
        path = ".".join(str(p) for p in loc)
        message = error["msg"].removeprefix("Value error, ")
        out.append(f"{where}: {path}: {message}" if path else f"{where}: {message}")
    return out


def parse(soil_text: str) -> SoilReport | list[str]:
    """The soil report, or its problems. The placeholder file of a new project is empty."""
    try:
        data = json.loads(soil_text) if soil_text.strip() else {}
    except json.JSONDecodeError as exc:
        return [f"Soil report: not valid JSON ({exc.msg}, line {exc.lineno})"]
    if is_placeholder(data) or data == {}:
        return SoilReport()
    try:
        return SoilReport.model_validate(data)
    except ValidationError as exc:
        return messages(exc, data)


def parse_boreholes(soil_text: str) -> tuple[SoilReport | None, list[str], list[str]]:
    """The report with only its valid boreholes, the problems of the others and their ids.

    One borehole with a mistake (overlapping layers, an SPT below its bottom, a repeated id)
    leaves the others to be computed. None (with the problems) when the report itself cannot
    be read: not JSON, or its design options or site are wrong."""
    try:
        data = json.loads(soil_text) if soil_text.strip() else {}
    except json.JSONDecodeError as exc:
        return None, [f"Soil report: not valid JSON ({exc.msg}, line {exc.lineno})"], []
    if is_placeholder(data) or data == {}:
        return SoilReport(), [], []
    try:
        return SoilReport.model_validate(data), [], []
    except ValidationError as exc:
        first = exc
    boreholes = data.get("boreholes") if isinstance(data, dict) else None
    if not isinstance(boreholes, list):
        return None, messages(first, data), []
    shell = {k: v for k, v in data.items() if k != "boreholes"}
    problems: list[str] = []
    bad: set[int] = set()
    seen: set[Any] = set()
    for i, hole in enumerate(boreholes):
        alone = {**shell, "boreholes": [hole]}
        try:
            SoilReport.model_validate(alone)
        except ValidationError as exc:
            bad.add(i)
            problems += messages(exc, alone)
            continue
        if hole.get("id") in seen:
            bad.add(i)
            problems.append(f"Soil report: two boreholes are called {hole.get('id')}")
        seen.add(hole.get("id"))
    kept = [hole for i, hole in enumerate(boreholes) if i not in bad]
    try:
        report = SoilReport.model_validate({**shell, "boreholes": kept})
    except ValidationError:
        return None, messages(first, data), []
    skipped = [
        str(hole.get("id") or f"borehole {i + 1}")
        if isinstance(hole, dict)
        else f"borehole {i + 1}"
        for i, hole in enumerate(boreholes)
        if i in bad
    ]
    return report, problems, skipped


def _failure(borehole: str, exc: Exception, problems: list[str], details: list[str]) -> None:
    """A borehole the computation failed on: a short problem, the traceback for the details."""
    problems.append(f"{borehole}: its results could not be computed ({type(exc).__name__}: {exc})")
    details.append(f"{borehole}:\n" + "".join(traceback.format_exception(exc)))


def _settings(settings_text: str | None) -> tuple[ProjectSettings, list[str]]:
    if not settings_text:
        return default_project_settings(), [
            "No project settings: the default code pack's values are used."
        ]
    try:
        return ProjectSettings.model_validate_json(settings_text), []
    except ValidationError:
        return default_project_settings(), [
            (
                "The project settings have errors: the default code pack's values are used for "
                "Z and the site class."
            )
        ]


def dumps(report: SoilReport) -> str:
    data = report.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(data, indent="\t", ensure_ascii=False) + "\n"


def _table_notes(rows: list[dict[str, Any]]) -> list[str]:
    """The bearing table's notes, each once with the founding depths it holds at when not all
    (a note of the fill under a 1 m footing does not hold for one at 2 m)."""
    depths = sorted({row["Df"] for row in rows})
    where: dict[str, set[int]] = {}
    for row in rows:
        for note in row["notes"]:
            where.setdefault(note, set()).add(row["Df"])
    out = []
    for note in sorted(where):
        at = sorted(where[note])
        if at == depths:
            out.append(note)
        else:
            out.append(f"at Df {', '.join(f'{d / 1e3:g}' for d in at)} m: {note}")
    return out


def _borehole(profile: Profile, site: dict[str, Any], screening: dict[str, Any]) -> dict[str, Any]:
    rows = bearing.table(profile)
    design = profile.design
    method = bearing.method_text(design)
    reference = bearing.allowable(
        profile,
        design.subgradeWidth / 1e3,
        design.subgradeWidth / 1e3,
        design.subgradeDepth / 1e3,
    )
    ks = piles.subgrade_modulus(profile, reference["qa"])
    reference_settlement = None
    if reference["qa"]:
        reference_settlement = rounded(
            settlement(
                profile,
                design.subgradeWidth / 1e3,
                design.subgradeWidth / 1e3,
                design.subgradeDepth / 1e3,
                reference["qa"],
            )
        )
    notes = _table_notes(rows)
    problem = problem_soils(profile)
    return {
        "id": profile.id,
        "x": profile.borehole.x,
        "y": profile.borehole.y,
        "groundLevel": round(profile.ground_level * 1e3, 1),
        "waterTable": profile.borehole.waterTable,
        "depth": round(profile.bottom * 1e3),
        "siteClass": site,
        "layers": [layer.to_json() for layer in profile.layers],
        "profile": profile.to_json(),
        "sptMethod": profile.spt_method,
        "liquefaction": screening,
        "bearing": {
            "table": [
                {k: row[k] for k in ("B", "Df", "qa_shear", "qa_settlement", "qa", "governs")}
                for row in rows
            ],
            "rows": rows,
            "method": method,
            "practice": design.practice,
            "factorOfSafety": design.factorOfSafety,
            "allowableSettlement": design.allowableSettlement,
            "notes": notes,
        },
        "settlement": reference_settlement,
        "permissibleSettlement": (
            reference_settlement["permissible"]
            if reference_settlement
            else settlement_permissible(
                "isolated",
                soil_column(profile, design.subgradeDepth / 1e3, 2 * design.subgradeWidth / 1e3),
            )
        ),
        "ks": ks["value"],
        "ksDetail": ks,
        "pile": piles.pile_parameters(profile, screening.get("layers")),
        "pileType": design.pile.type,
        "pileNote": piles.PILE_NOTES[design.pile.type],
        "lab": [lab.summary(s) for s in profile.borehole.samples],
        "problemSoils": problem,
        "notes": profile.notes
        + [
            f"{s.number or f'sample at {s.depth:g} mm'}: {flag}"
            for s in profile.borehole.samples
            for flag in lab.chemistry_flags(s)
        ]
        + [
            f"layer {soft['layer'] + 1} ({soft['top'] / 1e3:g}-{soft['bottom'] / 1e3:g} m): "
            f"{soft['consistency']} clay ({', '.join(soft['by'])}; {soft['clause']}): large and "
            "time-dependent settlement of shallow foundations, stability to check"
            for soft in problem["softClay"]
        ],
    }


def problem_soils(profile: Profile) -> dict[str, Any]:
    """The borehole's problem soils by the code pack's criteria: per sample the organic,
    expansive, collapsible and dispersive results (:mod:`saengine.soil.special_soils`), and the
    soft clay layers (by the layer's mean field N and its cu)."""
    samples = []
    for sample in profile.borehole.samples:
        grading = lab.grading_summary(sample.grading) if sample.grading is not None else None
        row = {
            "sample": sample.number,
            "depth": sample.depth,
            "organic": special_soils.organic(sample),
            "expansive": special_soils.expansive(sample, grading),
            "collapsible": special_soils.collapsible(sample),
            "dispersive": special_soils.dispersive(sample),
        }
        if any(row[k] is not None for k in ("organic", "expansive", "collapsible", "dispersive")):
            samples.append(row)
    soft = []
    for layer in profile.layers:
        blows = [
            r.blows
            for r in profile.borehole.spt
            if layer.top <= r.depth / 1e3 < layer.bottom and r.blows
        ]
        n = sum(blows) / len(blows) if blows else None
        found = special_soils.soft_clay(layer.behaviour, n, layer.cu)
        if found is not None:
            soft.append(
                {
                    "layer": layer.index,
                    "top": round(layer.top * 1e3),
                    "bottom": round(layer.bottom * 1e3),
                    "N": None if n is None else round(n, 1),
                    "cu": layer.cu,
                    **found,
                }
            )
    return {"samples": samples, "softClay": soft}


def classify(
    report: SoilReport, settings: ProjectSettings, profiles: list[Profile] | None = None
) -> dict[str, Any]:
    """The site class with the liquefaction screening behind its S2 flag.

    Returns ``{"sites", "project", "amax", "amaxNote", "screenings", "liquefiable"}``: the
    boreholes' site classes (with their flags), the project's (:func:`site_class.governing`),
    amax, each borehole's screening and the ids of the boreholes with liquefiable layers. When
    some borehole liquefies, the site is the pack's liquefiable class (S2 of the default pack):
    those boreholes' classes become the class assumed meanwhile (SD, if stiffer) for the design
    spectrum, and amax is worked out again with that class's S.
    """
    design = report.design
    profiles = profiles if profiles is not None else [Profile(report, b) for b in report.boreholes]
    from_spt = {p.id: site_class.site_class(p) for p in profiles}
    z = derived(settings)["Z"]

    def screen(
        sites: dict[str, dict[str, Any]], extra: list[str]
    ) -> tuple[float | None, str, dict[str, dict[str, Any]]]:
        project = site_class.governing(sites)
        classes = [settings.site.siteClass, *([project["class"]] if project["class"] else [])]
        amax, note = liquefaction.amax_from(design.liquefaction.pga, z, classes + extra)
        return amax, note, {p.id: liquefaction.screen(p, amax, note) for p in profiles}

    # S2 raises amax (the assumed class's S), which may make more boreholes liquefy: screen
    # again until the
    # set of liquefiable boreholes no longer grows (it only grows, so this ends).
    sites = from_spt
    liquefiable: set[str] = set()
    amax, amax_note, screenings = screen(sites, [])
    while True:
        found = liquefiable | {bh for bh, s in screenings.items() if s["layers"]}
        if found == liquefiable:
            break
        liquefiable = found
        sites = {
            bh: site_class.flag_liquefaction(site, bh in liquefiable)
            for bh, site in from_spt.items()
        }
        assumed = site_class.liquefiable_assumed()
        amax, amax_note, screenings = screen(sites, [assumed] if assumed else [])
    return {
        "sites": sites,
        "project": site_class.governing(sites),
        "amax": amax,
        "amaxNote": amax_note,
        "screenings": screenings,
        "liquefiable": sorted(liquefiable),
    }


def _site_class_text() -> str:
    """How the site class is found, with the pack in force's table."""
    r = site_class.rules()
    if r is None:
        return code_data.not_covered("The site class from the SPT")
    flags = [r.soft.siteClass if r.soft else None, r.liquefiableClass, r.rockDeepClass]
    flags = [f for f in flags if f]
    listing = ", ".join(flags[:-1]) + f" and {flags[-1]}" if len(flags) > 1 else "".join(flags)
    liquefiable = (
        f" ({r.liquefiableClass} when the screening finds liquefiable soil: "
        f"{r.liquefiableAssumed} is used meanwhile)"
        if r.liquefiableClass and r.liquefiableAssumed
        else ""
    )
    return (
        f"{r.clause}: harmonic mean N (field) and su over the top {float(r.depth):g} m; "
        f"{listing} are flags{liquefiable}"
    )


def soil_report(soil_text: str, settings_text: str | None = None) -> dict[str, Any]:
    """Everything computed from the soil report, per borehole and for the project."""
    report, problems, skipped = parse_boreholes(soil_text)
    if report is None:
        return {"problems": problems}
    settings, notes = _settings(settings_text)
    from saengine.codes import context as code_context
    from saengine.codes.registry import CodePackError

    try:
        pack = code_context.pack_for(settings)
    except CodePackError as exc:
        pack = None
        notes.append(f"The project's code pack cannot be used ({exc}): the default pack is used.")
    with code_context.using(pack):
        return _soil_report(report, problems, skipped, settings, notes)


def _soil_report(
    report: SoilReport,
    problems: list[str],
    skipped: list[str],
    settings: ProjectSettings,
    notes: list[str],
) -> dict[str, Any]:
    details: list[str] = []
    notes += check(report)
    design = report.design
    notes += _factor_of_safety_note(design.factorOfSafety)
    profiles = []
    for b in report.boreholes:
        try:
            profiles.append(Profile(report, b))
        except Exception as exc:  # noqa: BLE001 - one borehole must not blank the others
            _failure(b.id, exc, problems, details)
            skipped.append(b.id)
    try:
        classified = classify(report, settings, profiles)
    except Exception:  # noqa: BLE001 - find the borehole(s) it fails on and leave them out
        kept = []
        for p in profiles:
            try:
                classify(report, settings, [p])
                kept.append(p)
            except Exception as exc:  # noqa: BLE001
                _failure(p.id, exc, problems, details)
                skipped.append(p.id)
        profiles = kept
        classified = classify(report, settings, profiles)
    sites, screenings = classified["sites"], classified["screenings"]
    amax, amax_note, liquefiable = (
        classified["amax"],
        classified["amaxNote"],
        classified["liquefiable"],
    )
    project_site = classified["project"]
    if project_site["class"] and project_site["class"] != settings.site.siteClass:
        notes.append(
            f"The project settings use site class {settings.site.siteClass}; the boreholes give "
            f"{project_site['class']}. Update Project Settings → Site class."
        )
    boreholes = []
    for p in profiles:
        try:
            boreholes.append(_borehole(p, sites[p.id], screenings[p.id]))
        except Exception as exc:  # noqa: BLE001 - one borehole must not blank the others
            _failure(p.id, exc, problems, details)
            skipped.append(p.id)
    if liquefiable:
        notes.append(
            site_class.s2_note(
                project_site["class"] or site_class.liquefiable_assumed() or "",
            )
            + " Shallow foundations on liquefiable layers need ground improvement or piles "
            "through them."
        )
    adequacy = investigation.check(report)
    notes += adequacy.get("notes", [])
    site_chemistry = chemistry.site(report, *_sample_groups(profiles))
    if site_chemistry.get("concrete"):
        notes.append(chemistry.requirement_text(site_chemistry["concrete"]))
    governing_bh = next((b for b in boreholes if b["id"] == project_site.get("governing")), None)
    permissible = governing_bh["permissibleSettlement"] if governing_bh else None
    try:
        from saengine.soil.stratigraphy import build as build_stratigraphy

        strata_model: dict[str, Any] | None = build_stratigraphy(report)
    except Exception as exc:  # noqa: BLE001 - the 3D model must not blank the results
        strata_model = None
        notes.append(f"The 3D stratigraphy could not be built: {exc}")
    return {
        "stratigraphy": strata_model,
        "investigation": adequacy,
        "chemistry": site_chemistry,
        "boreholes": boreholes,
        "siteClass": project_site,
        "amax": amax,
        "amaxNote": amax_note,
        "practice": design.practice,
        "liquefactionMethod": design.liquefactionMethod,
        "permissibleSettlement": permissible,
        "methods": {
            "spt": profiles[0].spt_method if profiles else SPT_METHODS[design.practice],
            "bearing": bearing.method_text(design),
            "liquefaction": liquefaction.method_text(design.liquefactionMethod),
            "siteClass": _site_class_text(),
            "settlement": (
                f"Settlement criterion of qa: {design.allowableSettlement:g} mm (design option); "
                + permissible_text("isolated")
            ),
        },
        "notes": notes,
        # Per borehole; "problems" stays the key of a report that cannot be read at all.
        "warnings": problems,
        "skipped": skipped,
        "details": details,
    }


def _sample_groups(
    profiles: list[Profile],
) -> tuple[dict[tuple[str, int], str | None], dict[tuple[str, int], str | None]]:
    """Each sample's USCS group (the log's, else the suggested one) and the soil type of the
    layer it was taken in, by (borehole id, sample index), for the corrosivity score."""
    groups: dict[tuple[str, int], str | None] = {}
    types: dict[tuple[str, int], str | None] = {}
    for profile in profiles:
        hole = profile.borehole
        for i, sample in enumerate(hole.samples):
            layer = next(
                (lay for lay in hole.layers if lay.top <= sample.mid < lay.bottom),
                hole.layers[-1] if hole.layers else None,
            )
            suggested = lab.uscs_of(sample)
            groups[(hole.id, i)] = (layer.uscs if layer is not None and layer.uscs else None) or (
                suggested["symbol"] if suggested else None
            )
            types[(hole.id, i)] = layer.soilType if layer is not None else None
    return groups, types


def allowable_bearing(
    soil_text: str,
    settings_text: str | None,
    x_mm: float,
    y_mm: float,
    founding_level_mm: float,
    b_mm: float,
    l_mm: float,
) -> dict[str, Any]:
    """Net allowable pressure for a footing B × L whose underside is at ``founding_level_mm``
    (project datum) at plan position (x, y): the nearest borehole's, or the lowest of the
    boreholes within 10 m. No value (``qa_kpa`` None, with the reason) when any of those
    boreholes gives none: one without strength data under the base could be the weakest.

    qa is net of the total overburden at the founding level of the governing borehole, measured
    from its ground level: the result gives both (``groundLevel`` [mm], ``overburden`` [kPa]),
    so the footing's net pressure can take off the same overburden."""
    del settings_text  # qa does not depend on the project settings (kept for the RPC shape)
    report = parse(soil_text)
    if isinstance(report, list):
        return {"problems": report}
    if not report.boreholes:
        return {
            "qa_kpa": None,
            "qa_shear": None,
            "qa_settlement": None,
            "borehole": None,
            "method": bearing.method_text(report.design),
            "note": "The soil report has no boreholes.",
        }
    b, l_ = min(b_mm, l_mm) / 1e3, max(b_mm, l_mm) / 1e3
    distances = sorted(
        ((math.hypot(bh.x - x_mm, bh.y - y_mm), bh) for bh in report.boreholes),
        key=lambda item: item[0],
    )
    near = [(d, bh) for d, bh in distances if d <= NEARBY] or distances[:1]
    results = []
    for d, bh in near:
        profile = Profile(report, bh)
        df = (report.ground_level(bh) - founding_level_mm) / 1e3
        result = bearing.allowable(profile, b, l_, max(df, 0.0))
        results.append((d, bh, df, result, profile))
    missing = [r for r in results if r[3]["qa"] is None]
    if missing:
        _, bh, _, result, _ = missing[0]
        reasons = "; ".join(result["notes"]) or "no strength data under the base"
        within = " (within 10 m)" if len(near) > 1 else ""
        return {
            "qa_kpa": None,
            "qa_shear": None,
            "qa_settlement": None,
            "borehole": bh.id,
            "method": bearing.method_text(report.design),
            "note": f"No allowable pressure: {bh.id}{within} gives none: {reasons}.",
            "notes": [n for r in missing for n in r[3]["notes"]],
        }
    d, bh, df, result, profile = min(results, key=lambda r: r[3]["qa"])
    parts = [
        f"{bh.id}, {d / 1e3:.1f} m away, Df = {df:.2f} m below its ground"
        + (" (founding above the ground: Df = 0)" if df < 0 else "")
    ]
    if len(near) > 1:
        others = ", ".join(f"{o.id} {r['qa']:.0f} kPa" for _, o, _, r, _ in results)
        parts.append(f"lowest of the boreholes within 10 m ({others})")
    elif d > NEARBY:
        parts.append("no borehole within 10 m: the nearest is used")
    parts.append(f"governed by {result['governs']}")
    return {
        "qa_kpa": result["qa"],
        "qa_shear": result["qa_shear"],
        "qa_settlement": result["qa_settlement"],
        "borehole": bh.id,
        "Df": round(df * 1e3),
        "groundLevel": round(report.ground_level(bh)),
        "overburden": round(profile.sigma_v(max(df, 0.0)), 2),
        # The soil at the founding level and the water table below the base [mm] (negative:
        # above it; None: not measured), for the depth and presumptive-value rules.
        "foundingSoil": _founding_soil(profile, max(df, 0.0)),
        "waterDepth": (
            None if profile.water_table is None else round((profile.water_table - df) * 1e3)
        ),
        "method": bearing.method_text(report.design),
        "note": "; ".join(parts) + ".",
        "notes": result["notes"],
    }


def _factor_of_safety_note(value: float) -> list[str]:
    """A warning when the factor of safety on the bearing capacity lies outside the range of
    the code pack in force (its ``foundations.shallow.factorOfSafety``); none when the pack
    gives no range."""
    from saengine.codes import context as code_context

    try:
        table = code_context.table("foundations")
    except Exception:  # noqa: BLE001 - a pack without the table gives no range
        return []
    shallow = getattr(table, "shallow", None)
    if shallow is None:
        return []
    low, high = shallow.factorOfSafety
    if low <= value <= high:
        return []
    where = table.sources.get("shallow.factorOfSafety", "")
    return [
        f"The factor of safety on the bearing capacity, {value:g}, is outside {low:g}-{high:g}"
        + (f" ({where})" if where else "")
    ]


def _founding_soil(profile: Profile, df: float) -> str | None:
    """ "cohesive" or "granular" for the layer at the founding level (rock counts as granular,
    its depth rule being the cohesionless one or less); None when there is no layer."""
    layer = profile.layer_at(df + 1e-3)
    if layer is None:
        return None
    return "cohesive" if layer.behaviour == "cohesive" else "granular"


def footing_settlement(
    soil_text: str,
    borehole: str,
    b_mm: float,
    l_mm: float,
    df_mm: float,
    q_kpa: float,
    foundation: str = "isolated",
) -> dict[str, Any]:
    """Settlement of a footing at a borehole under a net pressure (for the editor), with the
    code pack's permissible value for the ``foundation`` ("isolated" or "raft"; BNBC 2020
    Table 6.3.8 in the default pack)."""
    if foundation not in ("isolated", "raft"):
        return {"problems": [f"Unknown foundation type {foundation!r}: isolated or raft."]}
    report = parse(soil_text)
    if isinstance(report, list):
        return {"problems": report}
    found = next((bh for bh in report.boreholes if bh.id == borehole), None)
    if found is None:
        return {"problems": [f"There is no borehole {borehole}."]}
    profile = Profile(report, found)
    return rounded(
        settlement(profile, b_mm / 1e3, l_mm / 1e3, df_mm / 1e3, q_kpa, foundation=foundation)
    )
