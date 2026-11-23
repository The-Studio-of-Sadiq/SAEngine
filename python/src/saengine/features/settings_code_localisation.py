"""Project Settings - Code Localisation tab: language, regional formats, templates, terminology, units, locale."""

from __future__ import annotations

from typing import Any

from saengine import units as units_lib
from saengine.codes import catalogue, registry
from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.settings_common import active_pack, load_settings


@feature(
    "settingsCodeLocalisation.interfaceLanguage",
    "Interface Language",
    part="settings",
    fields=[
        select(
            "language",
            "Interface & report language",
            [("en", "English"), ("bn", "বাংলা (Bangla)")],
            "en",
        ),
    ],
    requires_project=False,
)
def interface_language(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect active project language and supported report localisation options."""
    st = load_settings(ctx)
    return result(
        summary={"activeLanguage": st.project.language, "selectedLanguage": values["language"]},
        tables=[
            table(
                "Language settings",
                [("scope", "Scope"), ("code", "Code")],
                [
                    {"scope": "Project settings", "code": st.project.language},
                    {"scope": "Requested preview", "code": values["language"]},
                ],
            )
        ],
        notes=[
            "Report headings and labels translate while engineering symbols and units stay invariant."
        ],
    )


@feature(
    "settingsCodeLocalisation.unitLabels",
    "Unit Labels",
    part="settings",
    fields=[],
    requires_project=False,
)
def unit_labels(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List standard SI and US unit symbols used across reports and drawings."""
    st = load_settings(ctx)
    u = units_lib.units_of(st)
    rows = [
        {"quantity": k, "siLabel": kind.si, "activeLabel": u.unit(k)}
        for k, kind in list(units_lib.KINDS.items())[:12]
    ]
    return result(
        summary={"unitSystem": st.units.system, "labelCount": len(rows)},
        tables=[
            table(
                "Unit symbol labels",
                [
                    ("quantity", "Quantity"),
                    ("siLabel", "SI label"),
                    ("activeLabel", "Active display"),
                ],
                rows,
            )
        ],
        notes=["Unit symbols remain ASCII/Unicode engineering notation across languages."],
    )


@feature(
    "settingsCodeLocalisation.translationCheck",
    "Translation Check",
    part="settings",
    fields=[],
    requires_project=False,
)
def translation_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview bilingual structural terminology pairs for report translation verification."""
    pairs = [
        ("Dead Load", "স্থায়ী ভার"),
        ("Live Load", "অস্থায়ী ভার"),
        ("Wind Load", "বায়ু ভার"),
        ("Seismic Load", "ভূমিকম্প ভার"),
        ("Bearing Capacity", "মাটির ভারবহন ক্ষমতা"),
    ]
    rows = [{"english": en, "bangla": bn} for en, bn in pairs]
    return result(
        summary={"checkedTerms": len(rows), "projectLanguage": load_settings(ctx).project.language},
        tables=[
            table(
                "Bilingual terminology check",
                [("english", "English"), ("bangla", "Localised")],
                rows,
            )
        ],
        notes=["Verifies UTF-8 rendering of localized engineering terms."],
    )


@feature(
    "settingsCodeLocalisation.applyLanguage",
    "Apply Language",
    part="settings",
    fields=[
        select("targetLang", "Target language", [("en", "English"), ("bn", "বাংলা (Bangla)")], "en"),
    ],
    requires_project=False,
)
def apply_language(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate language pack availability and report affected output artefacts."""
    packs = [
        p for p in registry.default_registry().list_packs(ctx.root, "languagePack") if p.effective
    ]
    return result(
        summary={
            "targetLanguage": values["targetLang"],
            "installedPacks": len(packs),
            "requiresRestart": False,
        },
        tables=[
            table(
                "Language application scope",
                [("artifact", "Output"), ("localised", "Translated")],
                [
                    {"artifact": "Calculation reports", "localised": True},
                    {"artifact": "Drawing title blocks", "localised": True},
                    {"artifact": "Code clause citations", "localised": False},
                ],
            )
        ],
        notes=["Report regeneration reflects project.language immediately."],
    )


@feature(
    "settingsCodeLocalisation.numberFormat",
    "Number Format",
    part="settings",
    fields=[
        number("value", "Sample numeric value", 98765.432),
        select(
            "grouping",
            "Digit grouping",
            [
                ("western", "Western (3-digit: 98,765.43)"),
                ("southAsian", "South Asian (2,2,3: 9,87,65.43)"),
            ],
            "western",
        ),
    ],
    requires_project=False,
)
def loc_number_format(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview Western vs South Asian lakh/crore digit grouping conventions."""
    v = values["value"]
    if values["grouping"] == "western":
        out = f"{v:,.2f}"
    else:
        whole, frac = f"{v:.2f}".split(".")
        if len(whole) > 3:
            last3 = whole[-3:]
            rest = whole[:-3]
            groups = []
            while len(rest) > 2:
                groups.append(rest[-2:])
                rest = rest[:-2]
            if rest:
                groups.append(rest)
            out = ",".join(reversed(groups)) + "," + last3 + "." + frac
        else:
            out = f"{v:.2f}"
    return result(
        summary={"grouping": values["grouping"], "formatted": out},
        tables=[
            table(
                "Number grouping preview",
                [("style", "Style"), ("formatted", "Output")],
                [{"style": values["grouping"], "formatted": out}],
            )
        ],
        notes=["Supports international and South Asian regional numeric grouping."],
    )


@feature(
    "settingsCodeLocalisation.dateFormat",
    "Date Format",
    part="settings",
    fields=[
        select(
            "fmt",
            "Date style",
            [("iso", "2026-11-23"), ("eu", "23.11.2026"), ("us", "11/23/2026")],
            "iso",
        ),
    ],
    requires_project=False,
)
def date_format(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview regional date formatting for drawing revision tables and reports."""
    ex = {"iso": "2026-11-23", "eu": "23.11.2026", "us": "11/23/2026"}[values["fmt"]]
    return result(
        summary={"dateFormat": values["fmt"], "preview": ex},
        tables=[
            table(
                "Date format preview",
                [("format", "Format"), ("example", "Example")],
                [{"format": values["fmt"], "example": ex}],
            )
        ],
        notes=["Applied to title block revision dates and report headers."],
    )


@feature(
    "settingsCodeLocalisation.decimalSymbol",
    "Decimal Symbol",
    part="settings",
    fields=[
        select(
            "symbol", "Decimal separator", [("dot", "Period (.)"), ("comma", "Comma (,)")], "dot"
        ),
        number("sample", "Sample value", 28.75),
    ],
    requires_project=False,
)
def decimal_symbol(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview decimal separator rendering for CSV and tabular exports."""
    out = f"{values['sample']:.2f}"
    if values["symbol"] == "comma":
        out = out.replace(".", ",")
    return result(
        summary={"decimalSymbol": values["symbol"], "rendered": out},
        tables=[
            table(
                "Decimal symbol check",
                [("symbol", "Symbol"), ("rendered", "Output")],
                [{"symbol": values["symbol"], "rendered": out}],
            )
        ],
        notes=["CSV exports remain dot-delimited internally unless locale formatting is selected."],
    )


@feature(
    "settingsCodeLocalisation.formatPreview",
    "Format Preview",
    part="settings",
    fields=[],
    requires_project=False,
)
def format_preview(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview formatted forces, pressures, lengths, and dates under current project settings."""
    st = load_settings(ctx)
    u = units_lib.units_of(st)
    rows = [
        {"quantity": "Beam span", "formatted": u.format(6.5, "m")},
        {"quantity": "Slab thickness", "formatted": u.format(175.0, "mm")},
        {"quantity": "Live load", "formatted": u.format(2.5, "kN/m²")},
        {"quantity": "Column axial load", "formatted": u.format(1250.0, "kN")},
    ]
    return result(
        summary={"unitSystem": st.units.system, "language": st.project.language},
        tables=[
            table(
                "Formatted output preview",
                [("quantity", "Quantity"), ("formatted", "Display")],
                rows,
            )
        ],
        notes=["Generated using saengine.units.Units.from_settings."],
    )


@feature(
    "settingsCodeLocalisation.localTemplates",
    "Local Templates",
    part="settings",
    fields=[],
    requires_project=False,
)
def local_templates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List building templates matching regional market conventions."""
    bld = catalogue.building_templates(ctx.root)
    rows = [
        {"package": t["package"], "name": t["name"], "type": t["type"]} for t in bld["templates"]
    ]
    return result(
        summary={"templateCount": len(rows)},
        tables=[
            table(
                "Available local building templates",
                [("package", "Package"), ("name", "Name"), ("type", "Type")],
                rows,
            )
        ],
        notes=["Discovered via saengine.codes.catalogue.building_templates."],
    )


@feature(
    "settingsCodeLocalisation.regionalLibraries",
    "Regional Libraries",
    part="settings",
    fields=[],
    requires_project=False,
)
def regional_libraries(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List code packs grouped by country/region for regional section and material selection."""
    packs = [
        p
        for p in registry.default_registry().list_packs(ctx.root, "designCode")
        if p.effective and p.usable
    ]
    rows = [
        {
            "country": p.country or "-",
            "packId": p.id,
            "name": p.name,
            "units": "SI (internal)",
        }
        for p in packs[:25]
    ]
    return result(
        summary={
            "totalPacks": len(packs),
            "countriesRepresented": len({p.country for p in packs if p.country}),
        },
        tables=[
            table(
                "Regional code libraries",
                [
                    ("country", "Country"),
                    ("packId", "Pack ID"),
                    ("name", "Name"),
                    ("units", "Units"),
                ],
                rows,
            )
        ],
        notes=["Each regional code pack supplies localized towns, materials, and section tables."],
    )


@feature(
    "settingsCodeLocalisation.contentUpdates",
    "Content Updates",
    part="settings",
    fields=[],
    requires_project=False,
)
def content_updates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect installed code pack versions and verification timestamps."""
    st = load_settings(ctx)
    pack = active_pack(ctx, st)
    return result(
        summary={
            "activePack": pack.id,
            "version": pack.info.version,
            "verified": str(pack.info.verified or "-"),
        },
        tables=[
            table(
                "Content version status",
                [("pack", "Pack"), ("version", "Version"), ("verified", "Verified")],
                [
                    {
                        "pack": pack.id,
                        "version": pack.info.version,
                        "verified": str(pack.info.verified or "-"),
                    }
                ],
            )
        ],
        notes=["Offline mode: verify pack versions locally without network access."],
    )


@feature(
    "settingsCodeLocalisation.verifyContent",
    "Verify Content",
    part="settings",
    fields=[],
    requires_project=False,
)
def verify_content(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify that active code pack tables load cleanly without validation errors."""
    st = load_settings(ctx)
    pack = active_pack(ctx, st)
    broken = getattr(pack, "broken", {}) or {}
    return result(
        summary={
            "packId": pack.id,
            "loadedTables": len(pack.tables()),
            "brokenTables": len(broken),
            "healthy": len(broken) == 0,
        },
        tables=[
            table(
                "Content verification",
                [("table", "Broken table"), ("reason", "Reason")],
                [{"table": k, "reason": str(v[0].message)} for k, v in broken.items()]
                or [{"table": "all", "reason": "All pack tables validated cleanly"}],
            )
        ],
        notes=["Every table validated against Pydantic table schemas in saengine.codes.tables."],
    )


@feature(
    "settingsCodeLocalisation.keyTerms",
    "Key Terms",
    part="settings",
    fields=[],
    requires_project=False,
)
def key_terms(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect domain-specific terms defined in the active code pack."""
    st = load_settings(ctx)
    pack = active_pack(ctx, st)
    rows = [
        {"concept": "Seismic hazard input", "term": "Zone Z / Mapped spectral"},
        {"concept": "Structural system factor", "term": "Response reduction / Behaviour factor"},
        {"concept": "Active code basis", "term": pack.edition or pack.name},
    ]
    return result(
        summary={"packId": pack.id, "termCount": len(rows)},
        tables=[
            table(
                "Domain engineering terminology",
                [("concept", "Concept"), ("term", "Code pack term")],
                rows,
            )
        ],
        notes=["Terminology adapts automatically to the active code pack."],
    )


@feature(
    "settingsCodeLocalisation.standardGlossaries",
    "Standard Glossaries",
    part="settings",
    fields=[],
    requires_project=False,
)
def standard_glossaries(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List standard structural symbol glossary entries (D, L, W, E, φ, γ)."""
    rows = [
        {"symbol": "D / SD", "meaning": "Permanent dead / superimposed dead action"},
        {"symbol": "L / Lr", "meaning": "Floor / roof imposed live action"},
        {"symbol": "W / E", "meaning": "Wind / seismic lateral action"},
        {"symbol": "φ / γM", "meaning": "Resistance reduction / material partial factor"},
        {"symbol": "R / q", "meaning": "Seismic response modification / behaviour factor"},
    ]
    return result(
        summary={"glossaryEntries": len(rows)},
        tables=[
            table(
                "Engineering symbol glossary",
                [("symbol", "Symbol"), ("meaning", "Definition")],
                rows,
            )
        ],
        notes=["Consistent symbol legend printed in calculation report preambles."],
    )


@feature(
    "settingsCodeLocalisation.overrideTerms",
    "Override Terms",
    part="settings",
    fields=[
        text("defaultTerm", "Default term", "Slab"),
        text("customTerm", "Office/regional term", "Suspended Floor Plate"),
    ],
    requires_project=False,
)
def override_terms(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map default structural terminology to office-preferred labels for deliverables."""
    return result(
        summary={"defaultTerm": values["defaultTerm"], "customTerm": values["customTerm"]},
        tables=[
            table(
                "Terminology override",
                [("default", "Default"), ("custom", "Preferred")],
                [{"default": values["defaultTerm"], "custom": values["customTerm"]}],
            )
        ],
        notes=["Custom labels apply to report headings and drawing schedules."],
    )


@feature(
    "settingsCodeLocalisation.termAlignment",
    "Term Alignment",
    part="settings",
    fields=[],
    requires_project=False,
)
def term_alignment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit active pack basis labels against project drawings and report conventions."""
    st = load_settings(ctx)
    pack = active_pack(ctx, st)
    rows = [{"area": k, "basisLabel": v} for k, v in pack.basis.items()]
    return result(
        summary={"basisEntries": len(rows), "packId": pack.id},
        tables=[
            table(
                "Code basis label alignment",
                [("area", "Discipline"), ("basisLabel", "Basis label")],
                rows or [{"area": "general", "basisLabel": pack.edition or pack.name}],
            )
        ],
        notes=["Aligned with code pack basis metadata."],
    )


@feature(
    "settingsCodeLocalisation.unitSystem",
    "Unit System",
    part="settings",
    fields=[
        select(
            "system",
            "Primary display unit system",
            [("SI", "SI (Metric)"), ("USCustomary", "US Customary")],
            "SI",
        ),
    ],
    requires_project=False,
)
def loc_unit_system(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview switching project-wide display unit system."""
    st = load_settings(ctx)
    return result(
        summary={"currentSystem": st.units.system, "targetSystem": values["system"]},
        tables=[
            table(
                "Display unit switch preview",
                [("system", "System"), ("active", "Current")],
                [
                    {"system": "SI", "active": st.units.system == "SI"},
                    {"system": "USCustomary", "active": st.units.system == "USCustomary"},
                ],
            )
        ],
        notes=["Changing units.system affects display formatting only."],
    )


@feature(
    "settingsCodeLocalisation.imperialMetric",
    "Imperial Metric",
    part="settings",
    fields=[
        number("valueSi", "Sample SI length", 3.0, unit="m", min=0.0),
    ],
    requires_project=False,
)
def imperial_metric(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare metric and imperial presets side by side."""
    m = values["valueSi"]
    ft = m / units_lib.FOOT
    return result(
        summary={"metricM": m, "imperialFt": ft},
        tables=[
            table(
                "Metric vs Imperial preset",
                [("preset", "Preset"), ("length", "Length"), ("stress", "Stress")],
                [
                    {"preset": "SI Metric", "length": f"{m:.3f} m", "stress": "MPa"},
                    {"preset": "US Customary", "length": f"{ft:.3f} ft", "stress": "ksi"},
                ],
            )
        ],
        notes=["Instant comparison of metric and US customary output presets."],
    )


@feature(
    "settingsCodeLocalisation.precisionSettings",
    "Precision Settings",
    part="settings",
    fields=[
        number("dimDecimals", "Dimension decimal places", 1.0, min=0.0, max=4.0),
        number("forceDecimals", "Force decimal places", 1.0, min=0.0, max=4.0),
    ],
    requires_project=False,
)
def precision_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure decimal rounding precision for dimensional and force outputs."""
    return result(
        summary={
            "dimDecimals": int(values["dimDecimals"]),
            "forceDecimals": int(values["forceDecimals"]),
        },
        tables=[
            table(
                "Output precision",
                [("category", "Category"), ("decimals", "Decimals")],
                [
                    {"category": "Dimensions", "decimals": int(values["dimDecimals"])},
                    {"category": "Forces", "decimals": int(values["forceDecimals"])},
                ],
            )
        ],
        notes=["Applied to tabular summaries and calculation reports."],
    )


@feature(
    "settingsCodeLocalisation.convertUnits",
    "Convert Units",
    part="settings",
    fields=[
        number("inputValue", "Input value", 100.0),
        select(
            "fromUnit",
            "From unit",
            [
                ("kN", "kN"),
                ("kip", "kip"),
                ("kN/m²", "kN/m²"),
                ("psf", "psf"),
                ("m", "m"),
                ("ft", "ft"),
            ],
            "kN",
        ),
    ],
    requires_project=False,
)
def convert_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert an arbitrary engineering input between SI and US customary units."""
    v = values["inputValue"]
    fu = values["fromUnit"]
    conv = {
        "kN": ("kip", v * 1000.0 / units_lib.KIP),
        "kip": ("kN", v * units_lib.KIP / 1000.0),
        "kN/m²": ("psf", v * 1000.0 / (units_lib.POUND_FORCE / units_lib.FOOT**2)),
        "psf": ("kN/m²", v * (units_lib.POUND_FORCE / units_lib.FOOT**2) / 1000.0),
        "m": ("ft", v / units_lib.FOOT),
        "ft": ("m", v * units_lib.FOOT),
    }
    tu, res = conv[fu]
    return result(
        summary={"fromUnit": fu, "toUnit": tu, "convertedValue": res},
        tables=[
            table(
                "Unit conversion",
                [("from", "Input"), ("to", "Converted")],
                [{"from": f"{v:g} {fu}", "to": f"{res:.4f} {tu}"}],
            )
        ],
        notes=["Exact NIST conversion factors."],
    )


@feature(
    "settingsCodeLocalisation.regionalProfile",
    "Regional Profile",
    part="settings",
    fields=[],
    requires_project=False,
)
def regional_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise regional defaults (country, sheet size, units, language) from active code pack."""
    st = load_settings(ctx)
    pack = active_pack(ctx, st)
    rows = [
        {"setting": "Pack country", "value": pack.info.country or "-"},
        {"setting": "Suggested units", "value": pack.info.units or "SI"},
        {"setting": "Suggested sheet size", "value": pack.info.sheetSize or st.drawings.sheetSize},
        {"setting": "Project language", "value": st.project.language},
    ]
    return result(
        summary={
            "country": pack.info.country or "-",
            "units": pack.info.units or "SI",
            "sheetSize": st.drawings.sheetSize,
        },
        tables=[
            table(
                "Regional engineering profile", [("setting", "Setting"), ("value", "Value")], rows
            )
        ],
        notes=["Defaults come from the active code pack manifest."],
    )


@feature(
    "settingsCodeLocalisation.timezoneSetting",
    "Timezone Setting",
    part="settings",
    fields=[
        text("timezone", "IANA or UTC offset", "Asia/Dhaka"),
    ],
    requires_project=False,
)
def timezone_setting(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure display timezone for project audit logs and revision stamps."""
    return result(
        summary={"timezone": values["timezone"]},
        tables=[
            table(
                "Timezone configuration",
                [("setting", "Setting"), ("value", "Value")],
                [
                    {"setting": "Display timezone", "value": values["timezone"]},
                    {"setting": "Storage timezone", "value": "UTC"},
                ],
            )
        ],
        notes=["Timestamps are stored in UTC and formatted to the configured regional timezone."],
    )


@feature(
    "settingsCodeLocalisation.currencyFormat",
    "Currency Format",
    part="settings",
    fields=[
        text("symbol", "Currency symbol", "$"),
        number("amount", "Sample BOQ amount", 250000.0, min=0.0),
    ],
    requires_project=False,
)
def currency_format(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Format BOQ cost figures with regional currency symbol and placement."""
    formatted = f"{values['symbol']}{values['amount']:,.2f}"
    return result(
        summary={"symbol": values["symbol"], "formatted": formatted},
        tables=[
            table(
                "Currency format preview",
                [("symbol", "Symbol"), ("formatted", "Output")],
                [{"symbol": values["symbol"], "formatted": formatted}],
            )
        ],
        notes=["Applies to BOQ cost schedules and variation reports."],
    )


@feature(
    "settingsCodeLocalisation.localeFallback",
    "Locale Fallback",
    part="settings",
    fields=[
        select(
            "fallback",
            "Fallback language for untranslated keys",
            [("en", "English (en)"), ("pack", "Code pack native")],
            "en",
        ),
    ],
    requires_project=False,
)
def locale_fallback(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Specify fallback language policy when a regional pack omits a translation."""
    return result(
        summary={"fallbackLocale": values["fallback"]},
        tables=[
            table(
                "Locale fallback chain",
                [("priority", "Priority"), ("locale", "Locale")],
                [
                    {"priority": 1, "locale": load_settings(ctx).project.language},
                    {"priority": 2, "locale": values["fallback"]},
                ],
            )
        ],
        notes=["Ensures reports never print blank labels for untranslated terms."],
    )
