"""The design report as a document: the one model both the PDF and the Word file print.

:func:`report_document` lays the data of :func:`saengine.report.build.report_data` out as
sections of blocks, as a report template (:mod:`saengine.library.report_template`) chooses: which
sections, in what order, at what detail, with which cover and letterhead and which members. The
renderers only draw the blocks: ``templates/report.typ`` (Typst, PDF) and
:mod:`saengine.report.word` (Word). Neither knows the chapters, so the two never drift apart.

Blocks are plain JSON (every value text), ``{"t": kind, ...}``:

- ``h`` ``{level, text}``: a heading (level 1 is the section's own and starts a new page);
- ``p`` ``{text, strong?, size?, muted?}``: a paragraph, ``strong`` printed bold before it;
- ``pairs`` ``{rows, width}``: label/value rows;
- ``table`` ``{head, rows, columns, align, bad?, size}``: ``columns`` "auto", "1fr", "30%";
  ``align`` one of "l", "r", "c" per column; ``bad`` per row, true to highlight a failure;
- ``checks`` ``{title, ok, rows, fails, combination}``: every check of one element;
- ``bullets`` ``{items, size}``; ``note`` ``{text, strong?}``; ``empty`` ``{text}``;
- ``label`` ``{text, tone?}``: a bold caption that stays with what follows ("fail", "muted").

A block with ``"full": true`` is a calculation: a section printed at summary detail leaves it out.

Sections are built by the functions registered with :func:`register_section` under the ids of
:data:`saengine.library.report_template.SECTIONS`. Calculation worksheets plug in the same way
(id ``"worksheets"``): until a builder is registered for it the section has no content and is
skipped.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from saengine.library.report_template import (
    SECTIONS,
    MemberSelection,
    ReportTemplate,
    default_report_template,
)

Block = dict[str, Any]

# ─────────────────────────────────────── blocks ───────────────────────────────────────


def h(level: int, text: str) -> Block:
    return {"t": "h", "level": level, "text": text}


def p(text: str, *, strong: str = "", size: float | None = None, muted: bool = False) -> Block:
    block: Block = {"t": "p", "text": text}
    if strong:
        block["strong"] = strong
    if size:
        block["size"] = size
    if muted:
        block["muted"] = True
    return block


def pairs(rows: list[list[str]], width: str = "55%") -> Block:
    return {"t": "pairs", "rows": rows, "width": width}


def table(
    head: list[str],
    rows: list[list[str]],
    columns: list[str] | None = None,
    align: str | None = None,
    bad: list[bool] | None = None,
    size: float = 8.5,
) -> Block:
    n = len(head)
    block: Block = {
        "t": "table",
        "head": head,
        "rows": rows,
        "columns": columns or ["auto"] * n,
        "align": list(align or "l" * n),
        "size": size,
    }
    if bad is not None:
        block["bad"] = list(bad)
    return block


def checks(element: dict[str, Any], combination: str = "30%") -> Block:
    return {
        "t": "checks",
        "title": element["title"],
        "ok": bool(element["ok"]),
        "rows": element["rows"],
        "fails": element["fails"],
        "combination": combination,
    }


def bullets(items: list[str], size: float = 9) -> Block:
    return {"t": "bullets", "items": [str(i) for i in items], "size": size}


def note(text: str, strong: str = "") -> Block:
    block: Block = {"t": "note", "text": text}
    if strong:
        block["strong"] = strong
    return block


def empty(text: str) -> Block:
    return {"t": "empty", "text": text}


def label(text: str, tone: str | None = None) -> Block:
    block: Block = {"t": "label", "text": text}
    if tone:
        block["tone"] = tone
    return block


def full(*blocks: Block) -> list[Block]:
    """``blocks`` as calculations: left out of a section printed at summary detail."""
    return [{**b, "full": True} for b in blocks]


def method(text: str) -> Block:
    """The small grey method statement under a table."""
    return p(text, size=8.5, muted=True)


# ─────────────────────────────────────── sections ───────────────────────────────────────


class Context:
    """What a section builder needs besides the data: the detail it prints at, the template and
    the member selection, and the project warnings it may add to."""

    def __init__(self, template: ReportTemplate, detail: str, warnings: list[str]) -> None:
        self.template = template
        self.detail = detail
        self.members: MemberSelection = template.members
        self.warnings = warnings

    @property
    def summary(self) -> bool:
        return self.detail == "summary"


#: A section builder: the report data and the context → ``{"blocks", "title"?, "landscape"?}``,
#: or None when the project has nothing for the section.
SectionBuilder = Callable[[dict[str, Any], Context], dict[str, Any] | None]

_BUILDERS: dict[str, SectionBuilder] = {}


def register_section(section_id: str) -> Callable[[SectionBuilder], SectionBuilder]:
    """Registers the builder of a section (the hook calculation worksheets plug into)."""
    if section_id not in SECTIONS:
        raise ValueError(f"Unknown report section {section_id!r}: add it to SECTIONS first.")

    def register(builder: SectionBuilder) -> SectionBuilder:
        _BUILDERS[section_id] = builder
        return builder

    return register


def report_document(data: dict[str, Any], template: ReportTemplate | None = None) -> dict[str, Any]:
    """The document of the report ``data`` (from :func:`saengine.report.build.report_data`) as
    ``template`` chooses: ``{meta, status, warnings, cover, letterhead, contents, paper,
    sections: [{id, title, blocks, landscape}]}``. The appendix (landscape) prints last."""
    template = template or default_report_template()
    warnings = data.get("warnings", [])
    sections: list[dict[str, Any]] = []
    for choice in template.sections:
        if not choice.include:
            continue
        builder = _BUILDERS.get(choice.id)
        if builder is None:
            continue
        detail = template.detail if choice.detail == "inherit" else choice.detail
        built = builder(data, Context(template, detail, warnings))
        if not built or not built.get("blocks"):
            continue
        blocks = [
            {k: v for k, v in b.items() if k != "full"}
            for b in built["blocks"]
            if not (detail == "summary" and b.get("full"))
        ]
        sections.append(
            {
                "id": choice.id,
                "title": choice.title or built.get("title") or SECTIONS[choice.id],
                "detail": detail,
                "landscape": bool(built.get("landscape")),
                "blocks": blocks,
            }
        )
    sections.sort(key=lambda s: s["landscape"])  # stable: the landscape appendix goes last
    meta = data.get("meta", {})
    cover = template.cover
    firm = next((v for k, v in meta.get("titleBlock", []) if k == "Firm" and v), "")
    letter = template.letterhead
    return {
        "meta": {**meta, "title": cover.title},
        "status": data.get("status", {"state": "unchecked", "headline": ""}),
        "warnings": list(warnings),
        "template": {"id": template.id, "name": template.name, "detail": template.detail},
        "contents": template.contents,
        "paper": template.paper,
        "cover": {
            "show": cover.show,
            "title": cover.title,
            "subtitle": cover.subtitle or "",
            "status": cover.showStatus,
            "titleBlock": cover.showTitleBlock,
            "note": cover.note or "",
        },
        "letterhead": {
            "enabled": letter.enabled,
            "organisation": letter.organisation or firm,
            "lines": list(letter.lines),
            "logo": letter.logo or "",
        },
        "sections": sections,
    }


# ─────────────────────────────────────── member selection ───────────────────────────────────


def _selected(sel: MemberSelection, element_id: str, kind: str, storey: str, ok: bool) -> bool:
    if sel.kinds and kind not in sel.kinds:
        return False
    if sel.storeys and storey not in sel.storeys:
        return False
    if sel.ids and element_id not in sel.ids:
        return False
    return not (sel.failingOnly and ok)


def _utilisation(row: list[str], at: int) -> float:
    try:
        return float(row[at])
    except (ValueError, IndexError):
        return -1.0


def _member_table(t: dict[str, Any], ctx: Context) -> tuple[list[list[str]], list[bool], int]:
    """The rows of a member table the selection keeps (at summary detail: the failing ones and
    the governing one) and how many were left out."""
    storeys = t.get("storeys") or [""] * len(t["rows"])
    kept = [
        (row, bad)
        for row, bad, storey in zip(t["rows"], t["fails"], storeys, strict=False)
        if _selected(ctx.members, row[0], str(t.get("kind", "")), storey, not bad)
    ]
    if ctx.summary and kept:
        top = max(kept, key=lambda rb: _utilisation(rb[0], 6))
        kept = [rb for rb in kept if rb[1] or rb is top]
    return [r for r, _ in kept], [b for _, b in kept], len(t["rows"]) - len(kept)


def _selection_text(sel: MemberSelection) -> str:
    parts = []
    if sel.kinds:
        parts.append("kinds " + ", ".join(sel.kinds))
    if sel.storeys:
        parts.append("storeys " + ", ".join(sel.storeys))
    if sel.ids:
        parts.append("members " + ", ".join(sel.ids))
    if sel.failingOnly:
        parts.append("failing members only")
    return "; ".join(parts)


# ─────────────────────────────────────── design basis ───────────────────────────────────────


@register_section("basis")
def _basis(data: dict[str, Any], ctx: Context) -> dict[str, Any]:
    basis = data["basis"]
    out: list[Block] = []
    if "codes" in basis:
        out += [h(2, "Codes and method"), pairs(basis["codes"])]
    if "site" in basis:
        out += [h(2, "Building and site"), pairs(basis["site"])]
    if "seismic" in basis:
        out += [h(2, "Seismic force-resisting system"), pairs(basis["seismic"])]
    out.append(h(2, "Materials"))
    if basis["materials"]:
        out.append(
            table(
                ["Id", "Name", "Category", "Design strength", "E"],
                basis["materials"],
                ["auto", "1fr", "auto", "auto", "auto"],
            )
        )
    else:
        out.append(empty("The materials could not be read."))
    if "areaLoads" in basis:
        out += [
            h(2, "Area loads"),
            table(
                [
                    "Id",
                    "Name",
                    "Use",
                    "Live [kN/m²]",
                    "Concentrated [kN]",
                    "Finish [kN/m²]",
                    "Partitions [kN/m²]",
                ],
                basis["areaLoads"],
                ["auto", "1fr", "1fr", "auto", "auto", "auto", "auto"],
                "lllrrrr",
            ),
        ]
    out.append(h(2, "Load cases"))
    if basis["cases"]:
        out.append(table(["Case", "Description"], basis["cases"], ["auto", "1fr"]))
    else:
        out.append(empty("The analysis model has no static load cases."))
    if "combinations" in basis:
        combos = basis["combinations"]
        cols = list(combos["columns"])
        out += [
            h(2, "Load combinations"),
            p(
                "The strength design load combinations of the project settings ("
                + (combos.get("source") or "the code pack")
                + "); D includes the superimposed dead loads."
            ),
            *(p(note) for note in combos.get("notes", [])),
        ]
        if combos["rows"]:
            out += full(
                table(
                    ["Combination", *cols],
                    combos["rows"],
                    ["1fr"] + ["auto"] * len(cols),
                    "l" + "r" * len(cols),
                )
            )
        else:
            out.append(empty("There are no load combinations."))
    if "modelling" in basis:
        out += [
            h(2, "Analysis model and analyses"),
            pairs(basis["modelling"]),
            p(f"Analyses run: {', '.join(basis['analyses'])}."),
        ]
    return {"blocks": out}


# ─────────────────────────────────────── soil ───────────────────────────────────────


@register_section("soil")
def _soil(data: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    soil = data["soil"]
    if not soil.get("available"):
        return None
    bearing = soil["bearing"]
    out: list[Block] = [
        p(
            "From the soil report of the project (1 Soil Report). Depths are below each "
            "borehole's ground level; levels in the project datum."
        ),
        h(2, "Soil report"),
        pairs(soil["details"]),
        h(2, "Boreholes"),
        table(
            [
                "Borehole",
                "X [m]",
                "Y [m]",
                "Ground level [m]",
                "Water table [m]",
                "Depth [m]",
                "Layers",
                "SPT",
                "Site class",
            ],
            soil["boreholes"],
            ["auto"] * 8 + ["1fr"],
            "lrrrrrrrl",
            size=8,
        ),
        p("The water table is given as a depth below the borehole's ground level."),
    ]
    if soil["strata"]:
        out += [h(2, "Strata")] + full(
            table(
                [
                    "Borehole",
                    "Depth [m]",
                    "Soil",
                    "Description",
                    "γ [kN/m³]",
                    "cu [kPa]",
                    "φ' [°]",
                    "N60",
                ],
                soil["strata"],
                ["auto", "auto", "auto", "1fr", "auto", "auto", "auto", "auto"],
                "llllrrrr",
                size=7.5,
            )
        )
    site = soil["site"]
    out += [
        h(2, "Site class"),
        table(
            ["Borehole", "N̄", "s̄u [kPa]", "Class by N̄", "Class by s̄u", "Site class", "Over [m]"],
            site["rows"],
            ["auto"] * 6 + ["1fr"],
            "lrrcccl",
        ),
        bullets(site["notes"]),
        method(site["method"]),
        h(2, "Allowable bearing pressure"),
        p(
            "Net allowable bearing pressure qa (kPa) of square footings, the lowest of the "
            "boreholes for each width B and founding depth Df (– where a borehole gives none). "
            f"Factor of safety {bearing['factorOfSafety']} on shear; allowable settlement "
            f"{bearing['allowableSettlement']} mm. Each footing's own qa (at its position, "
            "founding level, B and L) is in its bearing check."
        ),
        table(
            ["B", *bearing["depths"]],
            bearing["rows"],
            ["1fr"] + ["auto"] * len(bearing["depths"]),
            "l" + "r" * len(bearing["depths"]),
        ),
    ]
    out += full(
        p(
            "The reference footing of each borehole, with its settlement and modulus of "
            "subgrade reaction:"
        ),
        table(
            [
                "Borehole",
                "B × Df [m]",
                "qa shear",
                "qa settlement",
                "qa [kPa]",
                "Governs",
                "Settlement [mm]",
                "ks [kN/m³]",
            ],
            bearing["reference"],
            ["auto"] * 5 + ["1fr", "auto", "auto"],
            "llrrrlrr",
            size=8,
        ),
    )
    if bearing["notes"]:
        out.append(bullets(bearing["notes"], 8.5))
    out.append(method(bearing["method"]))
    liq = soil["liquefaction"]
    out += [
        h(2, "Liquefaction screening"),
        table(
            ["Borehole", "Min. FS", "LPI", "Risk", "Liquefiable layers"],
            liq["rows"],
            ["auto"] * 4 + ["1fr"],
            "lrrll",
            bad=liq["fails"],
        ),
    ]
    if liq["notes"]:
        out.append(bullets(liq["notes"], 8.5))
    out.append(method(liq["method"]))
    return {"blocks": out}


# ─────────────────────────────────────── foundations ───────────────────────────────────────


@register_section("foundations")
def _foundations(data: dict[str, Any], ctx: Context) -> dict[str, Any]:
    fdn = data["foundations"]
    if not fdn.get("available"):
        return {"blocks": [note(str(fdn.get("message", "")))]}
    out: list[Block] = [
        p(
            "The foundations of 9 Substructure, designed for the support reactions of the "
            "analysis: the column bases are fixed supports of the analysis model. Bearing and "
            "pile loads are checked under the service combinations, the concrete (ACI 318-19) "
            "under the factored ones. Utilisation is demand over capacity; above 1.000 is "
            "marked FAIL."
        ),
        h(2, "Summary"),
        pairs(fdn["summary"], "40%"),
    ]
    if fdn["failed"]:
        out.append(
            note(
                "They are highlighted below.",
                f"{fdn['failed']} foundation(s) or tie beam(s) fail their design checks.",
            )
        )
    out += [
        h(2, "Governing checks"),
        table(
            ["Id", "Type", "Columns", "Size", "Governing check", "Util.", "Combination", "Result"],
            fdn["rows"],
            ["auto", "auto", "1fr", "auto", "1fr", "auto", "auto", "auto"],
            "lllllrlc",
            bad=fdn["fails"],
            size=8,
        ),
    ]
    if fdn["pressures"]:
        out += [
            h(2, "Bearing pressure"),
            p(
                "The largest net pressure under each footing and raft (the gross pressure less "
                "the overburden removed), against its net allowable bearing pressure qa."
            ),
            table(
                ["Foundation", "Net pressure [kPa]", "qa [kPa]", "Combination", "qa from"],
                fdn["pressures"],
                ["auto", "auto", "auto", "1fr", "auto"],
                "lrrll",
            ),
        ]
    if fdn["capacities"]:
        out += [
            h(2, "Pile capacity"),
            p(
                "Single-pile capacity at each pile cap (BNBC 2020 Part 6 Sec 3.10, geotechnical "
                "design of deep foundations): Qult = Qs + Qb - W, Qa the lesser of Qult / FS and "
                "the partial factors; Ta the allowable uplift."
            ),
            table(
                [
                    "Cap",
                    "Pile",
                    "Kind",
                    "Borehole",
                    "D [mm]",
                    "L [m]",
                    "Qs [kN]",
                    "Qb [kN]",
                    "Qult [kN]",
                    "FS",
                    "Qa [kN]",
                    "Ta [kN]",
                ],
                fdn["capacities"],
                ["auto"] * 12,
                "llll" + "r" * 8,
                size=7.5,
            ),
        ]
        for t in fdn.get("capacityTables", []):
            nd = len(t["diameters"])
            out += full(
                label(t["title"]),
                table(
                    ["Length", *t["diameters"]],
                    t["rows"],
                    ["1fr"] + ["auto"] * nd,
                    "l" + "r" * nd,
                    size=7.5,
                ),
            )
    if fdn["pileLoads"]:
        out += [h(2, "Pile loads")] + full(
            p(
                "The load on each pile (cap/pile; u, v its offset from the cap's centre in mm): "
                "service loads against Qa, factored loads for the pile section. Negative values "
                "are tension."
            ),
            table(
                [
                    "Pile",
                    "u",
                    "v",
                    "Service max [kN]",
                    "Service min [kN]",
                    "Factored max [kN]",
                    "Factored min [kN]",
                    "Qa [kN]",
                ],
                fdn["pileLoads"],
                ["auto"] * 8,
                "l" + "r" * 7,
                size=8,
            ),
        )
    if fdn["rafts"]:
        out += [
            h(2, "Rafts"),
            p(
                "Plate on compression-only Winkler springs (modulus of subgrade reaction ks); "
                "settlements are net of the rebound of the excavation."
            ),
            table(
                [
                    "Raft",
                    "ks [kN/m³]",
                    "Mesh [mm]",
                    "Net pressure [kPa]",
                    "qa [kPa]",
                    "Max contact [kPa]",
                    "Max settlement [mm]",
                    "Max differential [mm]",
                    "Angular distortion [‰]",
                ],
                fdn["rafts"],
                ["auto"] * 9,
                "l" + "r" * 8,
                size=7.5,
            ),
        ]
    if fdn["skipped"]:
        out += [
            h(2, "Foundations not designed"),
            table(["Id", "Type", "Reason"], fdn["skipped"], ["auto", "auto", "1fr"]),
        ]
    if fdn["details"]:
        out += full(h(2, "Checks of each foundation"), *[checks(e) for e in fdn["details"]])
    out += full(h(2, "Design method"), bullets(fdn["method"], 8.5))
    combos = fdn.get("combinations", {})
    if combos.get("service"):
        out += full(
            p(f"Service combinations: {', '.join(combos['service'])}."),
            p(f"Strength combinations: {', '.join(combos['strength'])}."),
        )
    return {"blocks": out}


# ─────────────────────────────────────── analysis model ───────────────────────────────────────


@register_section("model")
def _model(data: dict[str, Any], ctx: Context) -> dict[str, Any]:
    model = data["model"]
    out: list[Block] = [h(2, "Model summary"), pairs(model["rows"])]
    if model["derived"]:
        out += [h(2, "Equivalent static loads")] + full(
            p(
                "Values of the derivation of the analysis model from the building model and the "
                "project settings (BNBC 2020 6.2)."
            ),
            pairs(model["derived"]),
        )
    out += [
        h(2, "Analysis run"),
        table(
            ["Case", "Analysis", "Steps", "Status"],
            model["run"],
            ["1fr", "auto", "auto", "auto"],
            "llrl",
            bad=[row[3] != "Complete" for row in model["run"]],
        ),
    ]
    if model["runWarnings"]:
        out += [p("Warnings of the run:"), bullets(model["runWarnings"])]
    return {"blocks": out}


# ─────────────────────────────────────── analysis results ───────────────────────────────────────


def _serviceability_blocks(sv: dict[str, Any]) -> list[Block]:
    """B9: storey drift and sway under the service wind combination, overturning stability."""
    if not sv:
        return []
    if not sv.get("available"):
        return [h(2, "Serviceability"), p(str(sv.get("reason", "")))]
    out: list[Block] = [h(2, "Serviceability")]
    combos = ", ".join(sv.get("combinations") or [])
    if sv["drift"]:
        out += full(
            p(
                "Storey drift under loads other than earthquake: the largest storey drift ratio "
                f"along the wind under the service combinations ({combos}), the governing "
                f"storey per direction ({sv['driftClause']})."
            ),
            table(
                ["Dir.", "Combination", "Storey", "Δ/h [%]", "Limit [%]", "Basis", "Result"],
                sv["drift"],
                ["auto", "1fr", "auto", "auto", "auto", "1fr", "auto"],
                "lllrrlc",
                bad=sv["driftFails"],
            ),
        )
    if sv["sway"]:
        out += full(
            p(
                "Sway: the largest horizontal displacement of the top level along the wind over "
                f"the height above the base ({sv['swayClause']})."
            ),
            table(
                ["Dir.", "Combination", "Top [mm]", "H [m]", "Sway", "Limit", "Result"],
                sv["sway"],
                ["auto", "1fr"] + ["auto"] * 5,
                "llrrrrc",
                bad=sv["swayFails"],
            ),
        )
    if sv["overturning"]:
        out += full(
            p(
                "Overturning of the whole building: the base overturning moment of each lateral "
                "case against the dead load's resisting moment about the nearer edge of the "
                f"supports ({sv['overturningClause']}). {sv['overturningNote']}"
            ),
            table(
                [
                    "Case",
                    "M overturning [kN·m]",
                    "M resisting [kN·m]",
                    "Factor",
                    "Required",
                    "Result",
                ],
                sv["overturning"],
                ["1fr"] + ["auto"] * 5,
                "lrrrrc",
                bad=sv["overturningFails"],
            ),
        )
    if sv.get("notes"):
        out.append(bullets(sv["notes"], 8.5))
    return out


def _pushover_blocks(pushovers: list[dict[str, Any]]) -> list[Block]:
    """B20: the target displacement and the member acceptance of each pushover."""
    if not pushovers:
        return []
    out: list[Block] = [h(2, "Nonlinear static (pushover) analysis")]
    for push in pushovers:
        if not push.get("available"):
            out.append(p(f"{push['label']}: no target displacement ({push.get('reason', '')})."))
            continue
        out += full(
            p(f"{push['label']}: target displacement of the control point at the roof."),
            table(
                ["Quantity", "Value", "Clause"],
                push["target"],
                ["auto", "auto", "1fr"],
                "lrl",
            ),
        )
        out.append(p(str(push.get("acceptanceText", ""))))
        if push.get("acceptance"):
            out.append(
                table(
                    ["Member", "End", "Fibre", "Strain [‰]", "Limit [‰]", "Ratio", "Result"],
                    push["acceptance"],
                    ["1fr"] + ["auto"] * 6,
                    "lllrrrc",
                    bad=push.get("acceptanceFails"),
                )
            )
        if push.get("notes"):
            out.append(bullets([str(n) for n in push["notes"]], 8.5))
    return out


def _column_shortening_blocks(cs: dict[str, Any]) -> list[Block]:
    """B25: the column shortening with creep and shrinkage."""
    if not cs:
        return []
    out: list[Block] = [h(2, "Column shortening (creep and shrinkage)")]
    if not cs.get("available"):
        out.append(p(f"Not worked out: {cs.get('reason', '')}."))
        return out
    out.append(p(str(cs.get("intro", ""))))
    heads = ["Elastic [mm]", "Creep [mm]", "Shrinkage [mm]", "Total [mm]", "After casting [mm]"]
    if cs.get("levels"):
        out.append(
            table(
                ["Level (largest of the lines)", *heads],
                cs["levels"],
                ["1fr"] + ["auto"] * 5,
                "lrrrrr",
            )
        )
    if cs.get("lines"):
        out.append(
            table(["Column line (top)", *heads], cs["lines"], ["1fr"] + ["auto"] * 5, "lrrrrr")
        )
    if cs.get("differential"):
        out.append(
            table(
                ["Beam", "Level", "Span [m]", "Differential [mm]", "6EIΔ/L² [kN·m]"],
                cs["differential"],
                ["1fr"] + ["auto"] * 4,
                "llrrr",
            )
        )
    if cs.get("notes"):
        out.append(bullets(cs["notes"], 8.5))
    return out


def _nonstructural_blocks(ns: dict[str, Any]) -> list[Block]:
    """B15: seismic forces on nonstructural components and the anchorage of structural walls."""
    if not ns:
        return []
    out: list[Block] = [h(2, str(ns.get("title") or "Nonstructural components"))]
    if ns.get("intro"):
        out.append(p(str(ns["intro"])))
    if ns.get("rows"):
        n = len(ns["headers"])
        out.append(table(ns["headers"], ns["rows"], ["1fr"] + ["auto"] * (n - 1), "l" * n))
    if ns.get("anchorage"):
        n = len(ns["anchorageHeaders"])
        out.append(
            table(ns["anchorageHeaders"], ns["anchorage"], ["1fr"] + ["auto"] * (n - 1), "l" * n)
        )
    if ns.get("notes"):
        out.append(bullets([str(n) for n in ns["notes"]], 8.5))
    return out


def _irregularity_blocks(ir: dict[str, Any]) -> list[Block]:
    """B12: building irregularities, dynamic analysis, soft storeys, diaphragm connections."""
    if not ir:
        return []
    if not ir.get("available"):
        return [h(2, "Building irregularity"), p(str(ir.get("reason", "")))]
    out: list[Block] = [h(2, "Building irregularity")]
    out.append(
        p(
            f"Plan irregularities ({ir['planClause']}) and vertical irregularities "
            f"({ir['verticalClause']}) found in the building model and the static earthquake "
            "cases (the storey stiffness k = V / Δ of EX and EY, the floors' seismic weight, the "
            "storey strength estimated from the columns' and walls' shear strength)."
        )
    )
    if ir["findings"]:
        out.append(
            table(
                ["Irregularity", "Where", "Dir.", "Value", "Limit", "Clause"],
                ir["findings"],
                ["1fr", "1fr", "auto", "1fr", "auto", "1fr"],
                "llllll",
            )
        )
    else:
        out.append(empty("No irregularity was found."))
    if ir["storeys"]:
        out.append(
            table(
                [
                    "Storey",
                    "kX [kN/mm]",
                    "kY [kN/mm]",
                    "kX / above [%]",
                    "kY / above [%]",
                    "W [kN]",
                    "VnX [kN]",
                    "VnY [kN]",
                ],
                ir["storeys"],
                ["1fr"] + ["auto"] * 7,
                "lrrrrrrr",
            )
        )
    dynamic = ir.get("dynamic")
    if dynamic:
        if dynamic["required"]:
            text = (
                "Dynamic analysis is required: "
                + "; ".join(dynamic["reasons"])
                + ". "
                + (
                    "The design uses the response spectrum."
                    if dynamic["used"]
                    else "The design uses the equivalent static cases: choose the response "
                    "spectrum design."
                )
            )
        else:
            text = (
                f"Dynamic analysis is not required: height {dynamic['height']} m, limit "
                f"{dynamic['limit']} m in zone {dynamic['zone']} ({dynamic['clause']})"
                + (
                    ", but it is recommended for this irregular building."
                    if dynamic["recommended"]
                    else "."
                )
            )
        out.append(p(text))
    if ir["soft"]:
        out += full(
            p(f"Soft storeys, designed for {ir['softDesign']} ({ir['softClause']}):"),
            table(["Storey", "Dir.", "Found as"], ir["soft"], ["1fr", "auto", "1fr"], "lll"),
        )
    if ir.get("connections"):
        out.append(p(f"Diaphragm connections: {ir['connections']}."))
    if ir.get("notes"):
        out.append(bullets(ir["notes"], 8.5))
    return out


@register_section("results")
def _results(data: dict[str, Any], ctx: Context) -> dict[str, Any]:
    results = data["results"]
    out: list[Block] = []
    modal = results.get("modal")
    if modal:
        out += [
            h(2, "Modal periods and mass participation"),
            table(modal["columns"], modal["rows"], align="r" * len(modal["columns"])),
        ]
    out += [
        h(2, "Base reactions"),
        p("Sum of the support reactions of each load case, in global axes."),
    ]
    if results["reactions"]:
        out.append(
            table(
                ["Load case", "ΣFx [kN]", "ΣFy [kN]", "ΣFz [kN]"],
                results["reactions"],
                ["1fr", "auto", "auto", "auto"],
                "lrrr",
            )
        )
    else:
        out.append(empty("There are no static results."))
    if results["displacements"]:
        out += [
            h(2, "Displacements and story drifts"),
            table(
                [
                    "Load case",
                    "Max displacement [mm]",
                    "Max story drift [%]",
                    "Story",
                    "Cd·δ/I [%]",
                    "Allowable Δa/hsx [%]",
                    "Result",
                ],
                results["displacements"],
                ["1fr"] + ["auto"] * 6,
                "lrrlrrc",
                bad=results.get("displacementFails"),
            ),
        ]
    if results["notes"]:
        out.append(bullets(results["notes"], 8.5))
    out += _serviceability_blocks(results.get("serviceability") or {})
    out += _irregularity_blocks(results.get("irregularity") or {})
    out += _nonstructural_blocks(results.get("nonstructural") or {})
    out += _pushover_blocks(results.get("pushover") or [])
    out += _column_shortening_blocks(results.get("columnShortening") or {})
    rsd = results["seismicDesign"]
    if rsd.get("available"):
        out += [
            h(2, "Earthquake design from the response spectrum"),
            p(
                "The design combinations take E from the response spectrum cases (CQC of the "
                f"modes), Seismic Design Category {rsd['category']}. Where the dynamic base shear "
                f"is less than {rsd['fraction']} % of the equivalent static base shear, the "
                f"forces (not the drifts) are scaled up to it ({rsd['clause']})."
            ),
            table(
                [
                    "Direction",
                    "V static [kN]",
                    "V dynamic [kN]",
                    "V dyn / V static [%]",
                    "Scale",
                    "Mass [%]",
                ],
                rsd["scale"],
                align="lrrrrr",
            ),
            bullets(
                [
                    f"Orthogonal effects: {rsd['orthogonal']}.",
                    (
                        "Signs: response spectrum results have no sign; the design takes ± the "
                        "envelope, every force component at its peak (columns and walls at ±N, ±My, "
                        "±Mz)."
                    ),
                    (
                        f"Vertical component Ev = {rsd['vertical']} D (E = Eh + Ev with 1.2D, Eh − Ev "
                        "with 0.9D)."
                    ),
                ]
            ),
        ]
        if rsd["torsion"]:
            out += full(
                p(
                    "Accidental torsion, ±0.05 L F at each floor, added to the response spectrum "
                    f"of the same direction ({rsd['torsionClause']}):"
                ),
                table(
                    ["Case", "Level [m]", "F [kN]", "L [m]", "Mta [kN·m]"],
                    rsd["torsion"],
                    align="lrrrr",
                ),
            )
        if rsd["irregularity"]:
            out += full(
                p(
                    f"Torsional irregularity ({rsd['irregularityClause']}): the storey drift at "
                    "the two edges of the plan across the force, from the scaled response "
                    "spectrum ± the accidental torsion; irregular above 1.2 times the average, "
                    "extreme above 1.4. Where irregular in Seismic Design Category C or D the "
                    "accidental torsion is amplified by Ax = (δmax / 1.2 δavg)², at most 3.0 "
                    f"({rsd['amplificationClause']}): {rsd['torsionAmplification']}."
                ),
                table(
                    ["Dir.", "Storey", "Δmax [mm]", "Δavg [mm]", "Δmax / Δavg", "Torsion", "Ax"],
                    rsd["irregularity"],
                    ["auto", "1fr"] + ["auto"] * 5,
                    "llrrrlr",
                ),
            )
        if rsd["combinations"]:
            out.append(
                table(["Design combination with E", "Clause"], rsd["combinations"], ["1fr", "1fr"])
            )
        if rsd["drift"]:
            out += full(
                p(
                    "Design storey drift: the response spectrum drift (unscaled, the modal "
                    "combination of the modal drifts at each plan position, plus the accidental "
                    f"torsion) times Cd/I = {rsd['amplification']}, against the allowable storey "
                    "drift."
                ),
                table(
                    [
                        "Dir.",
                        "Storey",
                        "h [m]",
                        "Elastic [mm]",
                        "Cd·δ/I [mm]",
                        "Ratio [%]",
                        "Allowed [%]",
                        "Result",
                    ],
                    rsd["drift"],
                    ["auto", "1fr"] + ["auto"] * 6,
                    "llrrrrrc",
                    bad=rsd["driftFails"],
                ),
            )
            if rsd.get("driftRow"):
                out.append(p(f"Allowable storey drift: {rsd['driftRow']}."))
        if rsd.get("diaphragm"):
            out += full(
                p(
                    "Diaphragm in-plane deflection: the largest floor displacement relative to "
                    "the rigid motion of the floor's vertical elements, times Cd/I, against the "
                    f"permissible deflection of the attached elements ({rsd['diaphragmClause']})."
                ),
                table(
                    ["Dir.", "Level [m]", "Deflection [mm]", "Permissible [mm]", "Result"],
                    rsd["diaphragm"],
                    align="lrrrc",
                    bad=rsd["diaphragmFails"],
                ),
            )
        if rsd.get("separation"):
            out += full(
                p(
                    "Separation from adjacent structures against pounding, with the largest "
                    f"computed displacement δmax = {rsd['maxDisplacement']} mm "
                    f"({rsd['separationClause']})."
                ),
                table(
                    ["To", "Gap [mm]", "Required [mm]", "Basis", "Result"],
                    rsd["separation"],
                    ["1fr", "auto", "auto", "1fr", "auto"],
                    "lrrlc",
                    bad=rsd["separationFails"],
                ),
            )
        th = rsd.get("timeHistory")
        if th and th.get("suites"):
            used = (
                "The earthquake of the design combinations comes from these suites"
                if th["use"]
                else "The suites are checked but the design uses the response spectrum"
            )
            out += full(
                p(
                    f"Linear time histories: {used}. Each suite (records in one direction, or "
                    f"pairs applied simultaneously, {th['pairsClause']}) is scaled so that its "
                    "mean spectrum meets the code's criterion over its period range "
                    f"({th['recordsClause']}); the design value is the largest response below "
                    "the code's number of records and the mean from it, times the factor that "
                    f"lifts the base shear Vth to the static V ({th['responseClause']})."
                ),
                table(
                    [
                        "Suite",
                        "Records",
                        "Value",
                        "Least ratio",
                        "Vth [kN]",
                        "V [kN]",
                        "Factor",
                        "Used",
                    ],
                    th["suites"],
                    align="lrlrrrrc",
                ),
            )
            if th.get("drift"):
                out += full(
                    table(
                        [
                            "Suite",
                            "Dir.",
                            "Storey",
                            "h [m]",
                            "Drift [mm]",
                            "Cd·δ/I [mm]",
                            "Ratio [%]",
                            "Allowed [%]",
                            "Result",
                        ],
                        th["drift"],
                        align="lllrrrrrc",
                        bad=th["driftFails"],
                    ),
                )
        if rsd["notes"]:
            out.append(bullets(rsd["notes"], 8.5))
    so = results["secondOrder"]
    out += [
        h(2, "Section stiffness and second-order effects"),
        p(f"The analysis uses {so['stiffness']}."),
    ]
    if so.get("pDelta"):
        out.append(
            p(
                "It is a second-order (P-Delta) analysis: the columns have P-Delta "
                "transformations and every case is solved on the stiffness of the structure "
                "under the gravity preload (BNBC 2020 Part 6 Sec 2.5.7.9 and 6.3.10.4), so the "
                "sway moment magnification of the columns is taken as done; their magnification "
                "along the length (δns) still applies. Storey drift with and without P-Delta, and "
                "the stability coefficient θ = Px Δ / (Vx hsx Cd) of BNBC Eq. 6.2.48 (θ ≤ 0.10: "
                "P-Delta need not be considered; above θmax: redesign):"
            )
        )
        if so["rows"]:
            out += full(
                table(
                    ["Case", "Storey", "First order [%]", "P-Delta [%]", "Ratio", "θ", "θmax"],
                    so["rows"],
                    ["auto", "1fr"] + ["auto"] * 5,
                    "llrrrrr",
                    bad=so["fails"],
                )
            )
        if so["notes"]:
            out.append(bullets(so["notes"], 8.5))
    else:
        out.append(
            p(
                "It is a first-order analysis: the columns are designed for slenderness by "
                "moment magnification (BNBC 2020 Part 6 Sec 6.3.10.6 and 6.3.10.7, see Member "
                "design)."
            )
        )
    return {"blocks": out}


# ─────────────────────────────────────── member design ───────────────────────────────────────


@register_section("design")
def _design(data: dict[str, Any], ctx: Context) -> dict[str, Any]:
    design = data["design"]
    if not design.get("available"):
        return {
            "blocks": [
                note(str(design.get("problem", "")), "The member design checks could not be run:")
            ]
        }
    source = (
        "the static load cases, with the earthquake E from the scaled response spectrum (± the "
        "envelope, see Analysis results)"
        if design.get("seismicFromSpectrum")
        else "the static load cases"
    )
    out: list[Block] = [
        p(
            f"Design to {design['code']}. Forces are the factored combinations of {source}; "
            "utilisation is demand over design strength (φ applied). Elements whose utilisation "
            "exceeds 1.000 are marked FAIL (utilisations are printed to three decimals, as "
            "checked)."
        ),
        h(2, "Summary"),
        pairs(design["summary"], "40%"),
    ]
    if design["failed"]:
        where = (
            " and under Detailing checks that fail (Seismic detailing)"
            if (design.get("seismic") or {}).get("membersFail")
            else ""
        )
        failed = design.get("failedText") or f"{design['failed']} element(s)"
        out.append(
            note(
                f"They are highlighted in the tables below{where}.",
                f"{failed} fail their design checks.",
            )
        )
    if design.get("skipped"):
        kinds = ", ".join(f"{n} {k}" for k, n in design.get("notDesigned", {}).items())
        out.append(
            note(
                f"({kinds}): see Elements not designed. They are in no table of checks and must "
                "not be built as drawn.",
                f"{len(design['skipped'])} element(s) are not designed",
            )
        )
    chosen = _selection_text(ctx.members)
    if chosen:
        out.append(
            p(
                f"Member selection of this report: {chosen}. The summary and the design result "
                "count every member."
            )
        )
    if ctx.summary:
        out.append(
            p(
                "Summary detail: each table lists the failing members and the governing one; the "
                "full report lists every member."
            )
        )
    for t in design["tables"]:
        rows, bad, _ = _member_table(t, ctx)
        if not rows:
            continue
        out.append(h(2, t["title"]))
        if t["failed"]:
            out.append(label(f"{t['failed']} of {t['count']} fail.", "fail"))
        else:
            out.append(label(f"All {t['count']} pass.", "muted"))
        out.append(
            table(
                [
                    "Element",
                    "Type",
                    "Governing check",
                    "Demand",
                    "Capacity",
                    "Unit",
                    "Util.",
                    "Combination",
                    "Result",
                ],
                rows,
                ["auto", "auto", "1fr", "auto", "auto", "auto", "auto", "1fr", "auto"],
                "lllrrlrlc",
                bad=bad,
                size=8,
            )
        )
    req = design.get("required") or {}
    if req.get("available") and req.get("tables"):
        out += full(
            h(2, "Reinforcement required"),
            p(
                "The steel each object type requires (flexure with the minimum steel, shear and "
                "ties, as the design checks) next to the bars entered, at the location of its "
                "members that needs the most. Required and provided are areas per bar group "
                "(mm²) or per metre width (mm²/m); for column ties the spacing (mm) is the "
                "largest allowed and the one entered."
            ),
        )
        for t in req["tables"]:
            out += full(
                label(t["title"]),
                table(
                    [
                        "Type",
                        "Members",
                        "Governing",
                        "Required",
                        "Provided",
                        "Unit",
                        "Short",
                        "Result",
                    ],
                    t["rows"],
                    ["auto", "auto", "1fr", "auto", "auto", "auto", "auto", "auto"],
                    "lrlrrllc",
                    bad=t["bad"],
                    size=8,
                ),
            )
        if req.get("lines"):
            out += full(bullets(req["lines"]))
    wl = design.get("walls") or {}
    if wl.get("piers"):
        out += [
            h(2, "Wall piers"),
            p(
                "Each wall is designed by its piers (the wall between openings in a storey; "
                "under a window the whole wall at its bottom level too), from section cuts of "
                "the shell model (BNBC 2020 Part 6 Sec 6.6, 6.4.8; special structural walls Sec "
                "8.3.6). Forces of the governing combination at the cut it governs (else the "
                "pier's bottom): P [kN, compression +], V2 [kN], M3 [kN·m]."
            ),
            table(
                [
                    "Wall",
                    "Pier",
                    "Storey",
                    "lw [mm]",
                    "tw [mm]",
                    "P",
                    "V2",
                    "M3",
                    "Governing check",
                    "Util.",
                    "Result",
                ],
                wl["piers"],
                ["auto"] * 8 + ["1fr", "auto", "auto"],
                "lllrrrrrlrc",
                bad=wl.get("piersBad"),
                size=7.5,
            ),
        ]
        if wl.get("boundary"):
            out += full(
                label("Boundary elements (Sec 8.3.6.6)"),
                table(
                    [
                        "Wall",
                        "Pier",
                        "Method",
                        "Test",
                        "Boundary element",
                        "Length [mm]",
                        "Height [mm]",
                    ],
                    wl["boundary"],
                    ["auto", "auto", "auto", "1fr", "auto", "auto", "auto"],
                    "lllllrr",
                    size=8,
                ),
            )
        if wl.get("coupling"):
            out += full(
                label("Coupling beams (Sec 8.3.6.7)"),
                table(
                    [
                        "Wall",
                        "Spandrel",
                        "ln / h [mm]",
                        "Bars",
                        "Governing check",
                        "Util.",
                        "Result",
                    ],
                    wl["coupling"],
                    ["auto"] * 4 + ["1fr", "auto", "auto"],
                    "llrllrc",
                    bad=wl.get("couplingBad"),
                    size=8,
                ),
            )
    sm = design.get("steel") or {}
    if sm.get("members"):
        out += [
            h(2, "Steel members"),
            p(
                "Structural steel beams, columns and braces by LRFD to BNBC 2020 Part 6 Chapter "
                "10: the section (hollow sections with the design wall thickness 0.93 t), its "
                "local buckling class, the mass [kg/m], the unbraced lengths and K, and the "
                "governing check; every check is in the member's own checks below."
            ),
            table(
                [
                    "Member",
                    "Kind",
                    "Section",
                    "Material",
                    "Class",
                    "kg/m",
                    "Lengths",
                    "Governing check",
                    "Util.",
                    "Result",
                ],
                sm["members"],
                ["auto"] * 6 + ["1fr", "auto", "auto", "auto"],
                "lllllrllrc",
                bad=sm.get("membersBad"),
                size=7.5,
            ),
        ]
        if sm.get("connections"):
            out += full(
                label("Simple connections (Sec 10.10)"),
                table(
                    ["Member", "Connection", "Governing check", "Util.", "Result", "Assumptions"],
                    sm["connections"],
                    ["auto"] * 5 + ["1fr"],
                    "lllrcl",
                    bad=sm.get("connectionsBad"),
                    size=7.5,
                ),
            )
    st = design.get("stairs") or {}
    if st.get("parts"):
        out += [
            h(2, "Stairs"),
            p(
                "Flights and landings as one-way slabs per metre width (BNBC 2020 Part 6 Sec "
                "6.7): span [mm], thickness h [mm], factored load wu [kN/m²], moment Mu [kN·m/m] "
                "and shear Vu [kN/m]; the geometry checks are in the stair's own checks below."
            ),
            table(
                ["Stair", "Part", "Kind", "Span", "h", "wu", "Mu", "Vu", "Util.", "Result"],
                st["parts"],
                align="lllrrrrrrc",
                bad=st.get("partsBad"),
                size=8,
            ),
        ]
    li = design.get("lintels") or {}
    if li.get("rows"):
        out += [
            h(2, "Lintels"),
            p(
                "Lintels over the openings of masonry and partition walls, simply supported "
                "(BNBC 2020 Part 6 Sec 7.4.3.2): span [mm], section b × h [mm], Mu [kN·m], Vu "
                "[kN] and the bars designed."
            ),
            table(
                [
                    "Opening",
                    "Wall",
                    "Span",
                    "b × h",
                    "Mu",
                    "Vu",
                    "Bottom",
                    "Top",
                    "Links",
                    "Util.",
                    "Result",
                ],
                li["rows"],
                ["auto"] * 8 + ["1fr", "auto", "auto"],
                "llrcrrlllrc",
                bad=li.get("bad"),
                size=7.5,
            ),
        ]
    td = design.get("takedown") or {}
    if td.get("rows"):
        cases = list(td.get("cases") or [])
        out += [
            h(2, "Column load takedown"),
            p(
                f"{td.get('note')}. Per storey: what the storey adds [kN]; cumulative: at the "
                "column's foot [kN]."
            ),
            table(
                ["Line", "Storey", "Column"]
                + [f"{c} storey" for c in cases]
                + [f"{c} cum." for c in cases]
                + ["Total", "Factored"],
                td["rows"],
                align="lll" + "r" * (2 * len(cases) + 2),
                size=7,
            ),
        ]
    pu = design.get("punching") or {}
    if pu.get("rows"):
        out += [
            h(2, "Punching shear reinforcement"),
            p(
                "Headed shear studs (BNBC 2020 Part 6 Sec 6.4.10.5) or stirrups (6.4.10.3) round "
                "the columns where the concrete alone is not enough: elements per peripheral "
                "line, lines, first line from the column face and the spacing of the lines s0 / "
                "s [mm]; proposed unless the slab type gives them."
            ),
            table(
                [
                    "Slab",
                    "Column",
                    "Kind",
                    "Dia.",
                    "Per line",
                    "Lines",
                    "s0 / s",
                    "Util.",
                    "Result",
                ],
                pu["rows"],
                align="lllrrrrrc",
                bad=pu.get("bad"),
                size=8,
            ),
        ]
    if design.get("stability"):
        out += full(
            h(2, "Stability index Q per storey"),
            p(
                "Storeys are nonsway where Q = ΣPu Δo / (Vus lc) ≤ 0.05 (BNBC 2020 Part 6 Sec "
                "6.3.10.5.2, Eq. 6.6.17), at the combination with the largest Q."
            ),
            table(
                [
                    "Storey",
                    "Levels",
                    "Dir.",
                    "ΣPu [kN]",
                    "Vus [kN]",
                    "Δo [mm]",
                    "Q",
                    "Frame",
                    "δs",
                    "Combination",
                ],
                design["stability"],
                ["auto"] * 9 + ["1fr"],
                "lllrrrrlrl",
                size=8,
            ),
        )
    if design.get("slenderness"):
        out += full(
            h(2, "Slenderness"),
            p(
                "Column slenderness per bending axis (BNBC 2020 Part 6 Sec 6.3.10): k lu / r "
                "against the limit below which it may be neglected, the moment magnifiers δns "
                "and δs, and the governing moment M2 before and after magnification [kN·m]."
            ),
            table(
                [
                    "Column",
                    "Axis",
                    "Storey",
                    "Frame",
                    "k",
                    "k lu / r",
                    "Limit",
                    "δns",
                    "δs",
                    "M2 → Mc",
                ],
                design["slenderness"],
                ["auto"] * 9 + ["1fr"],
                "lcllrrrrrr",
                bad=design.get("slendernessFails"),
                size=8,
            ),
        )
    if design.get("skipped"):
        out += [
            h(2, "Elements not designed"),
            table(
                ["Element", "Kind", "Type", "Reason"],
                design["skipped"],
                ["auto", "auto", "auto", "1fr"],
            ),
        ]
    out += full(h(2, "Design method"), bullets(design["method"]))
    if design["combinations"]:
        out += full(p(f"Combinations checked: {', '.join(design['combinations'])}."))
    return {"blocks": out}


# ─────────────────────────────────────── seismic detailing ───────────────────────────────────


@register_section("seismic")
def _seismic(data: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    design = data["design"]
    sd = (design.get("seismic") or {}) if design.get("available") else {}
    if not sd.get("available"):
        return None
    out: list[Block] = [
        p(
            "Earthquake-resistant detailing to BNBC 2020 Part 6 Chapter 8 Sec 8.3 (pp. "
            "1088-1123). The detailing checks below count in each member's utilisation in Member "
            'design (their names start with "Detailing:").'
        ),
        pairs(sd["lines"], "45%"),
        h(2, "General requirements (Sec 8.3.2, 8.3.3)"),
        table(
            ["Requirement", "Result", "Note"],
            sd["checks"],
            ["2fr", "auto", "3fr"],
            "lcl",
            bad=sd["checksBad"],
            size=8,
        ),
    ]
    out += full(
        h(2, "Provisions that apply"),
        table(
            ["Section", "Title", "Page", "Applies", "Members"],
            sd["applies"],
            ["auto", "2fr", "auto", "auto", "1fr"],
            "lllcl",
            size=8,
        ),
    )
    if sd["members"]:
        if sd.get("membersFail"):
            out += [
                h(2, "Detailing checks that fail"),
                p(
                    "Every detailing check that fails: per object type, at its largest "
                    "utilisation, with the members it fails on; per beam-column joint (see "
                    "Beam-column joints below)."
                ),
            ]
        else:
            out += [
                h(2, "Members: governing detailing checks"),
                p(
                    "No detailing check fails. Per object type, the governing check, at its "
                    "largest utilisation."
                ),
            ]
        out.append(
            table(
                ["Type", "Kind", "Check", "Demand", "Limit", "Unit", "Util.", "Fails on"],
                sd["members"],
                ["auto", "auto", "2fr", "auto", "auto", "auto", "auto", "1fr"],
                "lllrrlrl",
                bad=sd["membersBad"],
                size=7.5,
            )
        )
    if sd["joints"]:
        out += full(
            h(2, "Beam-column joints"),
            p(
                'Strong column / weak beam ΣMnc / ΣMnb ≥ 1.2 (Sec 8.3.5.2, Eq. 6.8.5; "n.r.": '
                "not required, the columns carry at most 0.1 Ag f'c) and joint shear Vj against "
                "φVn = 0.85 γ √f'c Aj (Sec 8.3.7.3) [kN]."
            ),
            table(
                ["Joint", "Type", "Beams", "SCWB x", "SCWB y", "Vj", "φVn", "Util.", "Result"],
                sd["joints"],
                ["auto", "auto", "1fr"] + ["auto"] * 6,
                "lllrrrrrc",
                bad=sd["jointsBad"],
                size=8,
            ),
        )
    if sd["shears"]:
        out += full(
            h(2, "Capacity-design shear"),
            p(
                "Ve from the probable moments Mpr (1.25 fy, Sec 8.3.8.1) or the 2E combinations "
                "(Sec 8.3.10.3) against φVn [kN]; columns: the larger of their two directions."
            ),
            table(
                ["Member", "Kind", "Ve", "φVn", "Util.", "Result"],
                sd["shears"],
                align="llrrrc",
                bad=sd["shearsBad"],
                size=8,
            ),
        )
    if sd["notes"]:
        out += [h(2, "Notes"), bullets(sd["notes"], 8)]
    return {"blocks": out}


# ─────────────────────────────────────── planning ───────────────────────────────────


@register_section("planning")
def _planning(data: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    """The plot's planning compliance: the rules applied, the area statement and the checks."""
    plan = data.get("planning")
    if not plan:
        return None
    out: list[Block] = [p(str(plan.get("authority", "")), strong="Rules: ")]
    if plan.get("problems"):
        out.append(note(" ".join(plan["problems"]), "Not complete:"))
    num = lambda v, d=1: "-" if v is None else f"{v:,.{d}f}"
    rows = [
        ["Use", str(plan.get("useName") or plan.get("use") or "")],
        ["Plot area", f"{num(plan.get('plotArea'))} m² ({num(plan.get('katha'), 2)} katha)"],
        ["Plot size row", str(plan.get("band") or "")],
        ["Road width", "-" if plan.get("road") is None else f"{plan['road']:g} m"],
    ]
    allowed = plan.get("permitted")
    if allowed:
        rows.append(
            [
                "Permitted",
                f"FAR {allowed.get('farText')}, MGC {allowed['mgc']:g} % ({allowed['rule']})"
                if allowed["allowed"]
                else "not permitted",
            ]
        )
    limit = plan.get("heightLimit")
    if limit:
        rows.append(
            [
                "Height limit",
                f"{limit['storeys']} storeys, {limit['height']:g} m "
                + f"({limit['column']}; {limit['rule']})",
            ]
        )
    out.append(pairs(rows))
    areas, limits = plan.get("areas") or {}, plan.get("limits") or {}
    if areas:
        statement = [["Plot area", num(plan.get("plotArea")), ""]]
        statement.append(
            ["Ground coverage", num(areas.get("groundCoverage")), num(limits.get("mgcArea"))]
        )
        statement.append(
            [
                "Open space",
                num(areas.get("openSpace")),
                "" if not limits else f"≥ {num(limits.get('openSpace'))}",
            ]
        )
        for storey in areas.get("storeys") or []:
            statement.append([f"  {storey['name']}", num(storey["area"]), ""])
        statement.append(["Gross floor area", num(areas.get("grossFloorArea")), ""])
        if areas.get("excluded"):
            statement.append(["Less excluded", num(areas["excluded"]), ""])
        if areas.get("parking"):
            statement.append(["Less parking floors", num(areas["parking"]), ""])
        far_limit = limits.get("floorArea") if limits else None
        statement.append(
            [
                "Floor area for FAR",
                num(areas.get("farArea")),
                "not restricted" if limits and far_limit is None else num(far_limit),
            ]
        )
        out += [
            label("Area statement (m²)"),
            table(["", "Provided", "Limit"], statement, ["1fr", "auto", "auto"], "lrr"),
        ]
    checks = plan.get("checks") or []
    if checks:
        out += [
            label("Checks", None if plan.get("ok", True) else "fail"),
            table(
                ["Check", "Provided", "", "Limit", "Unit", "Result", "Rule"],
                [
                    [
                        c["label"],
                        f"{c['provided']:g}",
                        c["sense"],
                        "not restricted" if c["limit"] is None else f"{c['limit']:g}",
                        c["unit"],
                        "OK" if c["ok"] else ("advisory" if c.get("advisory") else "FAILS"),
                        c["rule"],
                    ]
                    for c in checks
                ],
                ["1fr", "auto", "auto", "auto", "auto", "auto", "30%"],
                "lrcrlcl",
                bad=[not c["ok"] and not c.get("advisory") for c in checks],
            ),
        ]
    if plan.get("notes"):
        out.append(bullets(plan["notes"], 8))
    return {"blocks": out}


# ─────────────────────────────────────── worksheets (hook) ───────────────────────────────────


@register_section("worksheets")
def _worksheets(data: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    """Calculation worksheets: the blocks of ``data["worksheets"]`` when a worksheet module put
    any there (each ``{title, blocks}``). Worksheets may instead register their own builder for
    this section."""
    sheets = data.get("worksheets") or []
    out: list[Block] = []
    for sheet in sheets:
        out.append(h(2, str(sheet.get("title", "Worksheet"))))
        out += list(sheet.get("blocks", []))
    return {"blocks": out} if out else None


# ─────────────────────────────────────── MEP ───────────────────────────────────────

_RESULT_COLUMNS = ["1fr", "auto", "auto", "auto", "auto", "auto"]
_RESULT_HEAD = ["Check", "Demand", "Capacity", "Unit", "Util.", "Result"]


def _unavailable(part: dict[str, Any], what: str) -> dict[str, Any] | None:
    if part.get("problem"):
        return {"blocks": [note(str(part["problem"]), f"The {what} could not be reported:")]}
    return None


@register_section("mep")
def _mep(data: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    mep = data["mep"]
    if not mep.get("available"):
        return _unavailable(mep, "MEP coordination")
    out: list[Block] = [
        p(
            "The building services of 7 MEP against the structure: the equipment's loads in the "
            "analysis model, the sleeves and openings through beams, slabs and walls checked, and "
            "the clashes of the services' IFC models with the structure."
        ),
        h(2, "Summary"),
        pairs(mep["summary"], "40%"),
    ]
    if mep["failed"]:
        out.append(
            note(
                "They are highlighted below.",
                f"{mep['failed']} sleeve(s) or opening(s) fail their checks.",
            )
        )
    if mep["partial"]:
        out.append(
            note(
                "their shear and flexure (or punching) checks need the analysis results; run the "
                "analysis and write the report again.",
                f"{mep['partial']} sleeve(s) or opening(s) are checked for their size and spacing "
                "only:",
            )
        )
    if mep["open"]:
        out.append(
            note(
                "give each a sleeve or opening, or reroute the service.",
                f"{mep['open']} hard clash(es) are not coordinated:",
            )
        )
    if mep["equipment"]:
        out += [
            h(2, "Equipment loads"),
            p(
                "Loads in kN by load case (SD the empty weight and plinth, F the contents, L any "
                "impact); pressure is the operating weight over the footprint [kPa]."
            ),
            table(
                ["Id", "Name", "Story", "On", "Loads [kN]", "Total [kN]", "Pressure"],
                mep["equipment"],
                ["auto", "1fr", "auto", "auto", "1fr", "auto", "auto"],
                "lllllrr",
                size=8,
            ),
        ]
    if mep["openings"]:
        out += [
            h(2, "Sleeves and openings"),
            table(
                ["Id", "Host", "Kind", "Governing check", "Util.", "Result"],
                mep["openings"],
                ["auto", "auto", "1fr", "1fr", "auto", "auto"],
                "llllrc",
                bad=mep["openingFails"],
                size=8,
            ),
        ]
    if mep["clashes"]:
        out += [
            h(2, "Clashes with the structure"),
            table(
                ["Id", "Service", "Structure", "Kind", "Status", "Note"],
                mep["clashes"],
                ["auto", "1fr", "auto", "auto", "auto", "1fr"],
                bad=mep["clashOpen"],
                size=8,
            ),
        ]
    out += full(h(2, "Method"), bullets(mep["method"]))
    return {"blocks": out}


@register_section("plumbing")
def _plumbing(data: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    plb = data["plumbing"]
    if not plb.get("available"):
        return _unavailable(plb, "plumbing")
    out: list[Block] = [
        p(
            "The plumbing of 7 MEP sized to BNBC 2020 Part 8 for its coordination with the "
            "structure: the water demand and storage, the risers and stacks with their sleeves "
            "and shafts, the water tanks, septic tank and reservoir with their reinforced "
            "concrete design, and the water-supply hydraulics. The plumbing design itself is the "
            "services engineer's."
        ),
        h(2, "Summary"),
        pairs(plb["summary"], "45%"),
    ]
    if plb["failed"]:
        out.append(note("They are highlighted below.", f"{plb['failed']} plumbing check(s) fail."))
    if plb["low"]:
        out.append(
            note(
                "raise the overhead tank or add a booster pump.",
                f"{plb['low']} floor(s) are below the minimum residual head:",
            )
        )
    if plb["stories"]:
        out += [
            h(2, "Demand"),
            p(
                "Daily demand by story (population × the per-capita requirement of Table 8.5.1) "
                "and the fixture units (supply: Appendix O Table 8.O.1; drainage: Table 8.6.12)."
            ),
            table(
                [
                    "Story",
                    "Occupancy",
                    "Persons",
                    "lpcd",
                    "Daily [l]",
                    "Supply units",
                    "Drainage units",
                ],
                plb["stories"],
                ["auto", "1fr"] + ["auto"] * 5,
                "llrrrrr",
                size=8,
            ),
        ]
    if plb["tanksRequired"]:
        out += [
            h(2, "Storage"),
            p(
                "Volumes in m³ (Sec 5.9.1.2(c)); drain and overflow diameters in mm (Tables "
                "8.5.2, 8.5.3)."
            ),
            table(
                ["Tank", "Kind", "Required", "Provided", "Drain", "Overflow", "Result"],
                plb["tanksRequired"],
                ["auto", "1fr"] + ["auto"] * 5,
                "llrrrrc",
                size=8,
            ),
        ]
    if plb["risers"]:
        out += [
            h(2, "Risers and stacks"),
            p(
                "Fixture units, flow [l/min] and diameters [mm]: the size the sleeves and shafts "
                "are coordinated with."
            ),
            table(
                ["Id", "System", "Units", "Flow", "Diameter", "Required", "Result"],
                plb["risers"],
                ["auto", "1fr"] + ["auto"] * 5,
                "llrrrrc",
                size=8,
            ),
        ]
    if plb["designs"]:
        out += full(h(2, "Tank design"))
        for d in plb["designs"]:
            out += full(h(3, d["title"]))
            if d.get("error"):
                out += full(note(str(d["error"]), "This tank could not be designed:"))
                continue
            out += full(pairs(d["rows"], "30%"))
            if d["failed"]:
                out += full(note("", f"{d['failed']} of {d['count']} checks fail."))
            out += full(
                p(f"The failing checks and the most utilised of its {d['count']} checks:"),
                table(_RESULT_HEAD, d["checks"], _RESULT_COLUMNS, "lrrlrc", bad=d["bad"], size=8),
            )
    if plb["floors"]:
        out += full(
            h(2, "Hydraulics"),
            p(
                "Residual head at the highest fixture of each floor and the static head on its "
                "fittings [m] (Table 8.5.6; at most 35 m, Sec 5.11)."
            ),
            table(
                ["Floor", "Riser", "Fixture level", "Head", "Required", "Static", "Result"],
                plb["floors"],
                ["1fr"] + ["auto"] * 6,
                "llrrrrc",
                bad=plb["floorFails"],
                size=8,
            ),
        )
    if plb["septic"]:
        out += [h(2, "Septic tank and soak well"), pairs(plb["septic"], "30%")]
    out += [
        h(2, "Checks"),
        table(
            _RESULT_HEAD, plb["checks"], _RESULT_COLUMNS, "lrrlrc", bad=plb["checkFails"], size=8
        ),
    ]
    out += full(h(2, "Method"), bullets(plb["method"]))
    return {"blocks": out}


@register_section("hvac")
def _hvac(data: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    hv = data["hvac"]
    if not hv.get("available"):
        return _unavailable(hv, "HVAC")
    out: list[Block] = [
        p(
            "The air-conditioning and ventilation of 7 MEP for their coordination with the "
            "structure (BNBC 2020 Part 8 Chapter 2): the cooling loads that size the plant, the "
            "plant's weights on the floors, the openings the ducts need through beams and slabs "
            "with their checks, and the shafts. The HVAC design itself is the services "
            "engineer's."
        ),
        h(2, "Summary"),
        pairs(hv["summary"], "40%"),
    ]
    if hv["failed"]:
        out.append(note("They are highlighted below.", f"{hv['failed']} HVAC check(s) fail."))
    if hv["zones"]:
        out += [
            h(2, "Cooling loads"),
            p(
                "Per story [kW], supply and outdoor air [m³/s], and when the peak occurs (month, "
                "time)."
            ),
            table(
                [
                    "Story",
                    "Area [m²]",
                    "Sensible",
                    "Latent",
                    "Total",
                    "Supply air",
                    "Outdoor air",
                    "Peak",
                ],
                hv["zones"],
                ["auto"] * 7 + ["1fr"],
                "lrrrrrrl",
                size=8,
            ),
        ]
    if hv["plant"]:
        out += [
            h(2, "Plant on the structure"),
            p(
                "Sizes [mm] (L x W x H), capacity (kW cooling, m³/s for fans and fresh-air "
                "units), operating weight [kN] and how the analysis loads it (dead load SD, the "
                "impact allowance of BNBC 2020 Part 6 Table 6.2.6 as live load for rotating "
                "plant)."
            ),
            table(
                ["Id", "Kind", "Story", "Size", "Capacity", "Weight", "In the analysis"],
                hv["plant"],
                ["auto", "1fr", "auto", "auto", "auto", "auto", "1fr"],
                "lllrrrl",
                size=8,
            ),
        ]
    out.append(h(2, "Duct openings"))
    if hv["openings"]:
        out += [
            p(
                "Openings the ducts still need, each passing its checks; they are added to 7 MEP "
                "by its Add Openings command (Run All reports them, it does not add them):"
            ),
            table(
                ["Opening", "Through", "Size [mm]", "For"],
                hv["openings"],
                ["auto", "auto", "auto", "1fr"],
                "llrl",
                size=8,
            ),
        ]
    else:
        out.append(empty("No duct opening is missing."))
    if hv["existing"]:
        out.append(
            p(
                f"Openings of 7 MEP the ducts pass through: {hv['existing']} (their checks are in "
                "the MEP coordination chapter)."
            )
        )
    if hv["conflicts"]:
        out += [
            p(
                "Ducts that cannot pass a beam or slab where they cross it, with the governing "
                "check and the routes that work:"
            ),
            table(
                ["Duct", "At", "Governing check (util.)", "Options"],
                hv["conflicts"],
                ["auto", "auto", "1fr", "1fr"],
                bad=[True] * len(hv["conflicts"]),
                size=8,
            ),
        ]
    if hv["shafts"]:
        out += [
            h(2, "Shafts"),
            table(
                ["Shaft", "Needed [m²]", "Area [m²]", "Result"],
                hv["shafts"],
                ["1fr", "auto", "auto", "auto"],
                "lrrc",
                size=8,
            ),
        ]
    out += [
        h(2, "Checks"),
        table(_RESULT_HEAD, hv["checks"], _RESULT_COLUMNS, "lrrlrc", bad=hv["checkFails"], size=8),
    ]
    if hv["method"]:
        out += full(h(2, "Method"), bullets(hv["method"]))
    return {"blocks": out}


@register_section("electrical")
def _electrical(data: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    el = data["electrical"]
    if not el.get("available"):
        return _unavailable(el, "electrical services")
    out: list[Block] = [
        p(
            "The electrical services of 7 MEP for their coordination with the structure (BNBC "
            "2020 Part 8 Chapter 1): the demand that sizes the substation and generator, their "
            "rooms, the equipment's weights on the floors, the rising mains and cable trays with "
            "the openings they need, and the lightning protection with the columns' reinforcement "
            "as down conductors and the foundations as the earth electrode. The electrical design "
            "itself is the services engineer's."
        ),
        h(2, "Summary"),
        pairs(el["summary"], "40%"),
    ]
    if el["failed"]:
        out.append(note("They are highlighted below.", f"{el['failed']} electrical check(s) fail."))
    if el["stories"]:
        out += [
            h(2, "Demand"),
            p(
                "Per story: Table 8.1.17's use, area [m²], unit load [W/m²], connected load [kW] "
                "and the maximum demand [kVA]."
            ),
            table(
                ["Story", "Use", "Area", "W/m²", "Connected", "kVA"],
                el["stories"],
                ["auto", "1fr", "auto", "auto", "auto", "auto"],
                "llrrrr",
                size=8,
            ),
        ]
    if el["equipment"]:
        out += [
            h(2, "Equipment on the structure"),
            p(
                "Rating (kVA, kW for PV, A for panels), size [mm], operating weight [kN] "
                "(typical where none is entered) and how the analysis loads it: dead load SD; a "
                "fuel tank's diesel as the fluid load F; a generator's impact as live load."
            ),
            table(
                ["Id", "Kind", "Story", "Rating", "Size", "Weight", "In the analysis"],
                el["equipment"],
                ["auto", "1fr", "auto", "auto", "auto", "auto", "1fr"],
                "lllrrrl",
                size=8,
            ),
        ]
    if el["rooms"]:
        out += [
            h(2, "Rooms"),
            table(
                _RESULT_HEAD, el["rooms"], _RESULT_COLUMNS, "lrrlrc", bad=el["roomFails"], size=8
            ),
        ]
    if el["risers"]:
        out += [
            h(2, "Rising mains"),
            table(
                ["Id", "Kind", "Size [mm]", "Rating [A]", "Current [A]", "Stories"],
                el["risers"],
                ["auto"] * 5 + ["1fr"],
                "llrrrl",
                size=8,
            ),
        ]
    if el["openings"]:
        out += [
            p(
                "Openings the risers and trays still need (added to 7 MEP by its Add Openings "
                "command):"
            ),
            table(
                ["Opening", "Through", "Size [mm]", "For"],
                el["openings"],
                ["auto", "auto", "auto", "1fr"],
                "llrl",
                size=8,
            ),
        ]
    lightning = el["lightning"]
    out.append(h(2, "Lightning protection and earthing"))
    if lightning.get("enabled"):
        out += [
            p(str(lightning["risk"])),
            p(
                f"Down conductors ({lightning['needed']} needed): the column lines whose "
                "reinforcement is made continuous from the foundation to the roof. For the "
                "structural drawings:"
            ),
            table(
                ["Id", "At (x, y) [mm]", "Columns", "Foundation", "Conductor"],
                lightning["conductors"],
                ["auto", "auto", "1fr", "auto", "auto"],
                "lrlll",
                size=8,
            ),
            bullets(lightning["structural"]),
        ]
    else:
        out += [empty("Lightning protection is not enabled in 7 MEP."), p(str(lightning["risk"]))]
    out += [
        h(2, "Checks"),
        table(_RESULT_HEAD, el["checks"], _RESULT_COLUMNS, "lrrlrc", bad=el["checkFails"], size=8),
    ]
    if el["method"]:
        out += full(h(2, "Method"), bullets(el["method"]))
    return {"blocks": out}


@register_section("fire")
def _fire(data: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    fi = data.get("fire") or {"available": False}
    if not fi.get("available"):
        return _unavailable(fi, "fire protection")
    out: list[Block] = [
        p(
            "The fire protection of 7 MEP for its coordination with the structure (BNBC 2020 "
            "Part 4): which systems the building needs and why, the fire water and its "
            "reservoir, the fire pumps and their room, the fire tanks designed as the plumbing "
            "tanks and their weights, the hanger and riser-support loads and the sleeves through "
            "the slabs and beams. The fire protection design itself is the services engineer's; "
            "values from NFPA are from memory, to be checked."
        ),
        h(2, "Summary"),
        pairs(fi["summary"], "40%"),
    ]
    if fi["failed"]:
        out.append(note("They are highlighted below.", f"{fi['failed']} fire check(s) fail."))
    plan = (
        f" A fire protection plan is required (Part 4 Sec 5.1.6): {fi['firePlan']}."
        if fi.get("firePlan")
        else ""
    )
    out += [
        h(2, "Systems required"),
        p(f"{fi['highRise']}{plan}"),
        table(
            ["System", "Part 4", "Designed", "Why"],
            fi["systems"],
            ["auto", "auto", "auto", "1fr"],
            "llcl",
            size=8,
        ),
    ]
    if fi["stories"]:
        out += [
            h(2, "Floors"),
            p(
                "Per story: the use (Part 3 group), the Table 4.4.1 hazard, the floor area [m²], "
                "the sprinkler heads (a layout estimate, Table 4.4.7), portable extinguishers, "
                "manual call points and detectors."
            ),
            table(
                ["Story", "Use", "Hazard", "Area", "Heads", "Ext.", "Call pts", "Detectors"],
                fi["stories"],
                ["auto", "1fr"] + ["auto"] * 6,
                "lllrrrrr",
                size=8,
            ),
        ]
    if fi["water"]:
        out += [h(2, "Fire water and pumps"), pairs(fi["water"], "30%")]
        if fi["requiredPumps"]:
            out += [
                p(
                    "Pump sets the duty needs (Table 4.4.2 rating; typical sizes [mm] and "
                    "operating weights [kN], to be replaced with the selected sets'):"
                ),
                table(
                    ["Pump", "Duty", "kW", "Size", "Weight"],
                    fi["requiredPumps"],
                    ["1fr"] + ["auto"] * 4,
                    "lrrrr",
                    size=8,
                ),
            ]
        if fi.get("pumpRoom"):
            out.append(p(f"Pump room: {fi['pumpRoom']}"))
    if fi["pumps"] or fi["tanks"]:
        out.append(h(2, "On the structure"))
        if fi["pumps"]:
            out.append(
                table(
                    ["Id", "Pump", "Story", "Duty", "kW", "Size", "In the analysis"],
                    fi["pumps"],
                    ["auto", "1fr"] + ["auto"] * 4 + ["1fr"],
                    "lllrrrl",
                    size=8,
                )
            )
        if fi["tanks"]:
            out += [
                p(
                    "Fire tanks (inside length x width x water depth [mm]), designed as the "
                    "plumbing tanks:"
                ),
                table(
                    ["Id", "Kind", "Size", "Design", "In the analysis"],
                    fi["tanks"],
                    ["auto", "auto", "auto", "1fr", "1fr"],
                    "llrll",
                    size=8,
                ),
            ]
    if fi["supports"]:
        out += full(
            h(2, "Hangers and riser supports"),
            p("Design loads for the inserts and anchors in the structure [kN]:"),
            table(
                ["Pipe", "Kind", "Spacing [m]", "Load", "Basis"],
                fi["supports"],
                ["auto"] * 4 + ["1fr"],
                "llrrl",
                size=8,
            ),
        )
    if fi["openings"]:
        out += [
            h(2, "Sleeves"),
            p(
                "Sleeves the fire risers and mains still need (added to 7 MEP by its Add Sleeves "
                "command):"
            ),
            table(
                ["Sleeve", "Through", "Dia. [mm]", "For"],
                fi["openings"],
                ["auto", "auto", "auto", "1fr"],
                "llrl",
                size=8,
            ),
        ]
    if fi["tests"]:
        out += full(
            h(2, "Test pressures"),
            table(
                ["System", "Pressure", "Basis"], fi["tests"], ["auto", "auto", "1fr"], "lrl", size=8
            ),
        )
    out += [
        h(2, "Checks"),
        table(
            [*_RESULT_HEAD, "Clause"],
            fi["checks"],
            [*_RESULT_COLUMNS, "1fr"],
            "lrrlrcl",
            bad=fi["checkFails"],
            size=8,
        ),
    ]
    if fi["method"]:
        out += full(h(2, "Method"), bullets(fi["method"]))
    return {"blocks": out}


# ─────────────────────────────────────── bill of quantities ───────────────────────────────────


@register_section("boq")
def _boq(data: dict[str, Any], ctx: Context) -> dict[str, Any]:
    boq = data["boq"]
    out: list[Block] = []
    if boq.get("status") != "ok":
        out.append(note(str(boq.get("message", ""))))
    groups = boq.get("groups") or []
    for g in groups:
        total = [["", "Total", g["total"], g["unit"]]] if g.get("total") else []
        out += [
            h(2, g["title"]),
            table(
                ["Item", "Description", "Quantity", "Unit"],
                g["rows"] + total,
                ["auto", "1fr", "auto", "auto"],
                "llrl",
            ),
        ]
    if not groups and boq.get("status") == "ok":
        out.append(empty("The bill of quantities has no items."))
    return {"blocks": out}


# ─────────────────────────────────────── limitations ───────────────────────────────────────


@register_section("limitations")
def _limitations(data: dict[str, Any], ctx: Context) -> dict[str, Any]:
    lim = data["limitations"]

    def notes(items: list[str]) -> list[Block]:
        return [bullets(items)] if items else [empty("No notes.")]

    out: list[Block] = [
        p(
            "These notes are printed as the analysis, design and quantity modules reported them. "
            "They state what the software did not check or assumed; the engineer must consider "
            "each one."
        )
    ]
    if data["warnings"]:
        out += [h(2, "Warnings"), bullets(data["warnings"])]
    if data["soil"].get("available"):
        out += [h(2, "Soil and foundations"), *notes(lim["soil"])]
    out += [h(2, "Foundations"), bullets(data["foundations"].get("limits", []))]
    if lim["foundations"]:
        out.append(bullets(lim["foundations"]))
    out += [h(2, "Member design"), *notes(lim["design"])]
    for key, title in (
        ("mep", "MEP coordination"),
        ("plumbing", "Plumbing"),
        ("hvac", "HVAC coordination"),
        ("electrical", "Electrical coordination"),
        ("fire", "Fire protection"),
    ):
        if (data.get(key) or {}).get("available"):
            out += [h(2, title), *notes(lim.get(key, []))]
    out += [h(2, "Bill of quantities"), *notes(lim["boq"])]
    out += [h(2, "Analysis model"), *notes(lim["model"])]
    if lim["run"]:
        out += [p("Warnings of the analysis run:"), bullets(lim["run"])]
    return {"blocks": out}


# ─────────────────────────────────────── appendix ───────────────────────────────────────


@register_section("appendix")
def _appendix(data: dict[str, Any], ctx: Context) -> dict[str, Any] | None:
    design = data["design"]
    if not design.get("available") or ctx.summary:
        return None
    details = [
        e
        for e in design.get("details", [])
        if _selected(
            ctx.members, e["id"], str(e.get("kind", "")), str(e.get("storey", "")), e["ok"]
        )
    ]
    if not details:
        return None
    scope = design.get("appendix") or {"scope": "all", "count": 0, "of": 0}
    if scope["scope"] == "governing":
        title = "Appendix: design checks of the governing elements"
        intro = (
            f"Every check, with the combination and position that govern it, of {len(details)} "
            f"of the {scope['of']} elements checked: for each object type and storey the element "
            "with the largest utilisation, and every element that fails. The member tables of "
            "Member design list the governing check of every element. (Project Settings → "
            'Design report → Appendix, or the report template\'s member selection: "all" prints '
            "every element.)"
        )
    else:
        title = "Appendix: design checks of every element"
        intro = "Every check of every element, with the combination and position that govern it."
    chosen = _selection_text(ctx.members)
    if chosen:
        intro += f" Member selection of this report: {chosen}."
    return {
        "title": title,
        "landscape": True,
        "blocks": [p(intro), *[checks(e, "34%") for e in details]],
    }
