"""Generates the ribbon catalog TypeScript from scripts/ribbon/ribbon_catalog.json.

    python scripts/ribbon/gen_ribbon_catalog.py

The catalog lists, per window and sub-window (a *scope*), the tabs, groups and buttons of the
ribbon (the owner's "visual first" round, 2026-11-23). A button whose feature exists runs its
command (``command`` in the JSON); the others open a planned-feature page that says what the
button will do. ribbonCatalog.contribution.ts registers them; ribbonRegistry.ts turns a scope
into its context rule.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Path(__file__).parent / "ribbon_catalog.json"
OUT = ROOT / "workbench/src/vs/workbench/contrib/saengineRibbon/browser/ribbonCatalog.generated.ts"

# The part a scope's planned features belong to (PROJECT_PARTS ids; others show no part line).
SCOPE_PARTS = {
    "soil": "soil",
    "settings": "settings",
    "materials": "materials",
    "objects": "objects",
    "plan": "floorPlan",
    "architecture": "bim",
    "bim": "bim",
    "mep": "mep",
    "fem": "fem",
    "foundations": "substructure",
    "boq": "boq",
    "documents": "exports",
    "studies": "studies",
    "exports": "exports",
    "overview": "overview",
}

ICONS_EXTRA = [
    ("pressure", "arrowDown"),
    ("settlement", "arrowDown"),
    ("water", "symbolColor"),
    ("flood", "symbolColor"),
    ("drain", "symbolColor"),
    ("liquef", "pulse"),
    ("spt", "symbolNumeric"),
    ("cpt", "symbolNumeric"),
    ("depth", "symbolRuler"),
    ("coordinate", "location"),
    ("crs", "location"),
    ("point", "location"),
    ("north", "compass"),
    ("kml", "globe"),
    ("surface", "layers"),
    ("profile", "graph"),
    ("modulus", "symbolNumeric"),
    ("factor", "symbolNumeric"),
    ("coefficient", "symbolNumeric"),
    ("ratio", "symbolNumeric"),
    ("number", "symbolNumeric"),
    ("format", "symbolNumeric"),
    ("currency", "creditCard"),
    ("limit", "shield"),
    ("rule", "law"),
    ("class", "symbolClass"),
    ("type", "symbolClass"),
    ("strength", "beaker"),
    ("cement", "beaker"),
    ("aggregate", "beaker"),
    ("cube", "beaker"),
    ("cylinder", "beaker"),
    ("sulfate", "beaker"),
    ("chloride", "beaker"),
    ("ph ", "beaker"),
    ("timber", "package"),
    ("glass", "package"),
    ("block", "package"),
    ("mortar", "package"),
    ("wall", "symbolStructure"),
    ("slab", "symbolStructure"),
    ("column", "symbolStructure"),
    ("beam", "symbolStructure"),
    ("member", "symbolStructure"),
    ("node", "symbolStructure"),
    ("diaphragm", "symbolStructure"),
    ("release", "symbolStructure"),
    ("support", "symbolStructure"),
    ("stair", "symbolStructure"),
    ("roof", "home"),
    ("room", "home"),
    ("ceiling", "home"),
    ("floor", "home"),
    ("finish", "paintcan"),
    ("colour", "paintcan"),
    ("color", "paintcan"),
    ("style", "paintcan"),
    ("sheet", "fileText"),
    ("title", "fileText"),
    ("page", "fileText"),
    ("pdf", "filePdf"),
    ("print", "filePdf"),
    ("photo", "deviceCamera"),
    ("text", "note"),
    ("label", "tag"),
    ("mark", "tag"),
    ("name", "tag"),
    ("log", "history"),
    ("revision", "versions"),
    ("compare", "versions"),
    ("custody", "shield"),
    ("purge", "trash"),
    ("merge", "groupByRefType"),
    ("split", "splitHorizontal"),
    ("trim", "edit"),
    ("move", "move"),
    ("offset", "move"),
    ("align", "move"),
    ("mirror", "mirror"),
    ("rotate", "compass"),
    ("duplicate", "copy"),
    ("paste", "copy"),
    ("hook", "symbolArray"),
    ("lap", "symbolArray"),
    ("stirrup", "symbolArray"),
    ("coupler", "symbolArray"),
    ("splice", "symbolArray"),
    ("spacing", "symbolRuler"),
    ("cover", "symbolRuler"),
    ("length", "symbolRuler"),
    ("thermal", "flame"),
    ("energy", "zap"),
    ("power", "zap"),
    ("parameter", "symbolProperty"),
    ("propert", "symbolProperty"),
    ("value", "symbolProperty"),
    ("default", "settingsGear"),
    ("preset", "settingsGear"),
    ("setup", "settingsGear"),
    ("recommend", "lightbulb"),
    ("favourite", "star"),
    ("exposure", "shield"),
    ("durab", "shield"),
    ("consequence", "shield"),
    ("easement", "map"),
    ("setback", "map"),
    ("zone", "map"),
]

# A button no keyword matches takes its window's icon.
SCOPE_ICONS = {
    "soil": "layers",
    "settings": "settingsGear",
    "materials": "beaker",
    "objects": "symbolStructure",
    "plan": "symbolStructure",
    "architecture": "home",
    "bim": "symbolMisc",
    "mep": "plug",
    "fem": "graph",
    "foundations": "arrowDown",
    "boq": "creditCard",
    "documents": "fileText",
    "studies": "telescope",
    "exports": "export",
    "overview": "dashboard",
}

CODICON_LIBRARY = ROOT / "workbench/src/vs/base/common/codiconsLibrary.ts"

# First keyword in a label (lower case) that picks the button's codicon.
ICONS = [
    ("import", "cloudDownload"),
    ("export", "export"),
    ("publish", "cloudUpload"),
    ("report", "fileText"),
    ("schedule", "table"),
    ("table", "table"),
    ("summary", "listFlat"),
    ("check", "pass"),
    ("audit", "checklist"),
    ("validate", "shield"),
    ("compliance", "shield"),
    ("clash", "warning"),
    ("chart", "graphLine"),
    ("curve", "graphLine"),
    ("plot", "graphLine"),
    ("graph", "graphLine"),
    ("diagram", "graph"),
    ("contour", "symbolColor"),
    ("map", "globe"),
    ("gis", "globe"),
    ("site", "location"),
    ("terrain", "globe"),
    ("soil", "layers"),
    ("strata", "layers"),
    ("layer", "layers"),
    ("borehole", "arrowDown"),
    ("pile", "arrowDown"),
    ("load", "arrowDown"),
    ("seismic", "pulse"),
    ("spectrum", "pulse"),
    ("vibration", "pulse"),
    ("modal", "pulse"),
    ("time history", "pulse"),
    ("wind", "symbolEvent"),
    ("cfd", "symbolEvent"),
    ("fire", "flame"),
    ("smoke", "flame"),
    ("sprinkler", "flame"),
    ("light", "lightbulb"),
    ("electr", "plug"),
    ("cable", "plug"),
    ("circuit", "circuitBoard"),
    ("panel", "circuitBoard"),
    ("duct", "symbolStructure"),
    ("pipe", "symbolStructure"),
    ("rebar", "symbolArray"),
    ("bar", "symbolArray"),
    ("section", "symbolRuler"),
    ("dimension", "symbolRuler"),
    ("measure", "symbolRuler"),
    ("grid", "symbolNumeric"),
    ("story", "layers"),
    ("storey", "layers"),
    ("level", "layers"),
    ("material", "beaker"),
    ("concrete", "beaker"),
    ("mix", "beaker"),
    ("test", "beaker"),
    ("cost", "creditCard"),
    ("rate", "creditCard"),
    ("price", "creditCard"),
    ("carbon", "globe"),
    ("time", "calendar"),
    ("phase", "calendar"),
    ("4d", "calendar"),
    ("view", "eye"),
    ("render", "eye"),
    ("camera", "deviceCamera"),
    ("filter", "filter"),
    ("search", "search"),
    ("find", "search"),
    ("select", "selection"),
    ("group", "groupByRefType"),
    ("tag", "tag"),
    ("note", "note"),
    ("comment", "comment"),
    ("markup", "edit"),
    ("issue", "issues"),
    ("task", "tasklist"),
    ("review", "eye"),
    ("history", "history"),
    ("version", "versions"),
    ("template", "fileCode"),
    ("library", "library"),
    ("catalog", "library"),
    ("database", "database"),
    ("mesh", "symbolMisc"),
    ("solve", "play"),
    ("run", "play"),
    ("analy", "play"),
    ("design", "tools"),
    ("optimi", "wand"),
    ("generate", "wand"),
    ("auto", "wand"),
    ("propose", "wand"),
    ("copy", "copy"),
    ("delete", "trash"),
    ("remove", "trash"),
    ("add", "add"),
    ("new", "add"),
    ("place", "add"),
    ("draw", "edit"),
    ("edit", "edit"),
    ("setting", "settingsGear"),
    ("option", "settingsGear"),
    ("unit", "symbolNumeric"),
    ("code", "law"),
    ("help", "question"),
    ("learn", "mortarBoard"),
    ("tutorial", "mortarBoard"),
]


def slug(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text)
    return (
        (words[0].lower() + "".join(w[:1].upper() + w[1:].lower() for w in words[1:]))
        if words
        else "x"
    )


def codicon_names() -> set[str]:
    text = CODICON_LIBRARY.read_text(encoding="utf-8")
    return set(re.findall(r"^\s+([a-zA-Z0-9]+): register", text, re.MULTILINE))


CODICONS = codicon_names()


def icon_for(label: str, scope: str) -> str:
    low = label.lower() + " "
    for word, icon in ICONS_EXTRA + ICONS:
        if word in low and icon in CODICONS:
            return icon
    return SCOPE_ICONS[scope.split(".")[0]]


def ts_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    scopes: dict[str, str] = catalog["scopes"]
    lines = [
        "/*---------------------------------------------------------------------------------------------",
        " *  Copyright (c) SAEngine contributors. All rights reserved.",
        " *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.",
        " *--------------------------------------------------------------------------------------------*/",
        "",
        "// GENERATED by scripts/ribbon/gen_ribbon_catalog.py from scripts/ribbon/ribbon_catalog.json. Do not edit.",
        "",
        "import { localize } from '../../../../nls.js';",
        "",
        "/** The tabs the catalog adds to the windows. */",
        "export type CatalogTabId =",
    ]
    tab_ids = [t["id"] for t in catalog["tabs"]]
    lines += [f"\t| '{t}'" for t in tab_ids[:-1]] + [f"\t| '{tab_ids[-1]}';", ""]
    scope_names = sorted(set(scopes.values()))
    lines += [
        "/** A window or sub-window: its tabs show only there (ribbonRegistry.ts scopeWhen). */",
        "export type RibbonScope =",
    ]
    lines += [f"\t| '{s}'" for s in scope_names[:-1]] + [f"\t| '{scope_names[-1]}';", ""]
    lines += [
        "export interface ICatalogTab {",
        "\treadonly id: CatalogTabId;",
        "\treadonly label: string;",
        "\treadonly scope: RibbonScope;",
        "}",
        "",
        "export const CATALOG_TABS: readonly ICatalogTab[] = [",
    ]
    for tab in catalog["tabs"]:
        lines.append(
            f"\t{{ id: '{tab['id']}', label: localize('ribbonCatalog.tab.{tab['id']}', {ts_string(tab['label'])}), scope: '{tab['scope']}' }},"
        )
    lines += ["];", "", "/** The scope of every tab the catalog fills, the existing ones too. */"]
    lines += ["export const CATALOG_TAB_SCOPES: Readonly<Record<string, RibbonScope>> = {"]
    lines += [f"\t{t}: '{s}'," for t, s in scopes.items()]
    lines += [
        "};",
        "",
        "export interface ICatalogButton {",
        "\t/** Command id: an existing command, or `saengine.catalog.<tab>.<slug>` for a planned feature. */",
        "\treadonly id: string;",
        "\treadonly planned: boolean;",
        "\treadonly label: string;",
        "\treadonly description: string;",
        "\treadonly size: 'large' | 'small';",
        "\t/** A Codicon name. */",
        "\treadonly icon: string;",
        "}",
        "",
        "export interface ICatalogGroup {",
        "\treadonly tab: string;",
        "\t/** The menu group, `<order>_<key>`; the key carries the label. */",
        "\treadonly group: string;",
        "\treadonly key: string;",
        "\treadonly label: string;",
        "\treadonly part: string;",
        "\treadonly buttons: readonly ICatalogButton[];",
        "}",
        "",
        "export const CATALOG_GROUPS: readonly ICatalogGroup[] = [",
    ]
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    order_by_tab: dict[str, int] = {}
    total = 0
    for group in catalog["groups"]:
        tab = group["tab"]
        order = order_by_tab.get(tab, 60)
        order_by_tab[tab] = order + 1
        key = (
            "cat"
            + tab[:1].upper()
            + tab[1:]
            + slug(group["group"])[:1].upper()
            + slug(group["group"])[1:]
        )
        # Two groups whose labels slug alike ("Risk & Reliability", "Risk Reliability").
        while key in seen_keys:
            key += "X"
        seen_keys.add(key)
        part = SCOPE_PARTS[scopes[tab].split(".")[0]]
        lines.append(
            f"\t{{ tab: '{tab}', group: '{order}_{key}', key: '{key}', label: localize('ribbonCatalog.group.{key}', {ts_string(group['group'])}), part: '{part}', buttons: ["
        )
        large = 0
        for button in group["buttons"]:
            command = button.get("command")
            bid = command or f"saengine.catalog.{tab}.{slug(button['label'])}"
            if bid in seen_ids:
                continue
            seen_ids.add(bid)
            size = "large" if button["size"] == "large" and large < 2 else "small"
            large += size == "large"
            nls = f"ribbonCatalog.{tab}.{slug(button['label'])}"
            lines.append(
                f"\t\t{{ id: '{bid}', planned: {'false' if command else 'true'}, label: localize('{nls}', {ts_string(button['label'])}), "
                f"description: localize('{nls}.d', {ts_string(button['description'])}), size: '{size}', icon: '{icon_for(button['label'], scopes[tab])}' }},"
            )
            total += 1
        lines.append("\t] },")
    lines += ["];", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"{len(catalog['groups'])} groups, {total} buttons -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
