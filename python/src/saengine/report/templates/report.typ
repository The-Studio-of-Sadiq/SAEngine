// SAEngine design report (Part 11 Exports). Copyright (c) SAEngine contributors.
// Licensed under the AGPL-3.0-only license.
//
// Lays out the data of saengine.report.build.report_data, passed as JSON in sys.inputs.data.
// Every value arrives as a string and is printed as text: user text needs no escaping here.

#let data = json(bytes(sys.inputs.at("data")))
#let meta = data.meta

#let ink = luma(20)
#let muted = luma(95)
#let rule = luma(175)
#let head-fill = luma(232)
#let fail-fill = rgb("#f9d9d6")
#let fail-ink = rgb("#a1150c")
#let warn-fill = rgb("#fdf1d6")

#set document(title: meta.title + " - " + meta.project, author: "SAEngine")
#set text(font: ("Libertinus Serif", "New Computer Modern"), size: 10pt, fill: ink, lang: "en")
#set par(justify: true, leading: 0.62em)
#set heading(numbering: "1.1")
#show heading.where(level: 1): it => {
  pagebreak(weak: true)
  set text(size: 15pt, weight: "bold")
  block(above: 0pt, below: 1em, it)
}
#show heading.where(level: 2): it => {
  set text(size: 11.5pt, weight: "bold")
  block(above: 1.4em, below: 0.7em, it)
}
#show heading.where(level: 3): it => {
  set text(size: 10pt, weight: "bold")
  block(above: 1.1em, below: 0.6em, it)
}

#set page(
  paper: "a4",
  margin: (left: 20mm, right: 18mm, top: 24mm, bottom: 22mm),
  header: context {
    if counter(page).get().first() > 1 {
      set text(size: 8pt, fill: muted)
      grid(
        columns: (1fr, auto),
        meta.project, meta.title,
      )
      v(-0.4em)
      line(length: 100%, stroke: 0.4pt + rule)
    }
  },
  footer: context {
    if counter(page).get().first() > 1 {
      set text(size: 8pt, fill: muted)
      line(length: 100%, stroke: 0.4pt + rule)
      v(-0.4em)
      grid(
        columns: (1fr, auto),
        [SAEngine #meta.version, #meta.isoDate], counter(page).display("1 / 1", both: true),
      )
    }
  },
)

// ───────────────────────────── helpers ─────────────────────────────

// A table of strings. `head`: column titles; `rows`: arrays of strings; `align`: per column;
// `bad`: per row, true to highlight it as a failure.
#let tbl(head, rows, columns: auto, align: none, bad: none, size: 8.5pt) = {
  let n = head.len()
  let aligns = if align == none { (left,) * n } else { align }
  set text(size: size)
  set par(justify: false)
  table(
    columns: if columns == auto { n } else { columns },
    align: (x, y) => aligns.at(x) + horizon,
    inset: (x: 4pt, y: 3.2pt),
    stroke: (x, y) => (
      top: if y == 0 { 0.8pt + ink } else { none },
      bottom: if y == 0 { 0.6pt + ink } else { 0.3pt + rule },
    ),
    fill: (x, y) => {
      if y == 0 { head-fill } else if bad != none and bad.at(y - 1, default: false) { fail-fill }
    },
    table.header(..head.map(h => text(weight: "bold", h))),
    ..rows.enumerate().map(((i, row)) => {
      let failing = bad != none and bad.at(i, default: false)
      row.map(cell => if failing and (cell == "FAIL") {
        text(weight: "bold", fill: fail-ink, cell)
      } else { cell })
    }).flatten(),
  )
}

// Label/value pairs as a two-column table without a header.
#let pairs(rows, width: 55%) = {
  set text(size: 9pt)
  set par(justify: false)
  table(
    columns: (width, 1fr),
    inset: (x: 4pt, y: 3pt),
    stroke: (x, y) => (bottom: 0.3pt + rule),
    ..rows.map(((label, value)) => (text(fill: muted, label), value)).flatten(),
  )
}

#let note(body) = block(
  width: 100%,
  inset: (x: 8pt, y: 6pt),
  fill: warn-fill,
  radius: 2pt,
  text(size: 9pt, body),
)

#let bullets(items, size: 9pt) = {
  set text(size: size)
  set par(justify: false)
  for item in items [- #item]
}

#let empty(body) = text(size: 9pt, style: "italic", fill: muted, body)

// ───────────────────────────── cover ─────────────────────────────

#page(header: none, footer: none, margin: (x: 25mm, top: 40mm, bottom: 25mm))[
  #set par(justify: false)
  #text(size: 10pt, fill: muted, tracking: 0.08em, upper(meta.title))
  #v(6mm)
  #text(size: 24pt, weight: "bold", meta.project)
  #v(4mm)
  #line(length: 100%, stroke: 1pt + ink)
  #v(8mm)
  #{
    set text(size: 10.5pt)
    table(
      columns: (45mm, 1fr),
      stroke: none,
      inset: (x: 0pt, y: 4pt),
      ..meta.details.map(((label, value)) => (text(fill: muted, label), value)).flatten(),
      text(fill: muted, "Code basis"), meta.code,
      text(fill: muted, "Date"), meta.date,
    )
  }
  #v(1fr)
  #if data.warnings.len() > 0 {
    note[
      *Read before use.* This report carries #data.warnings.len() warning(s), listed in the
      Limitations section.
    ]
    v(6mm)
  }
  #set text(size: 9pt, fill: muted)
  Prepared with SAEngine #meta.version (AGPL-3.0), typeset with Typst. \
  #meta.units
  #v(3mm)
  This report presents the results of computer analysis and design. It shall be reviewed,
  checked and signed by the structural engineer responsible for the design.
]

#counter(page).update(2)
#outline(title: [Contents], depth: 2, indent: auto)

// ───────────────────────────── 1 design basis ─────────────────────────────

= Design basis

#let basis = data.basis

#if "codes" in basis [
  == Codes and method
  #pairs(basis.codes)
]

#if "site" in basis [
  == Building and site
  #pairs(basis.site)
]

#if "seismic" in basis [
  == Seismic force-resisting system
  #pairs(basis.seismic)
]

== Materials
#if basis.materials.len() > 0 {
  tbl(
    ("Id", "Name", "Category", "Design strength", "E"),
    basis.materials,
    columns: (auto, 1fr, auto, auto, auto),
  )
} else { empty[The materials could not be read.] }

#if "areaLoads" in basis [
  == Area loads
  #tbl(
    ("Id", "Name", "Use", "Live [kN/m²]", "Finish [kN/m²]", "Partitions [kN/m²]"),
    basis.areaLoads,
    columns: (auto, 1fr, 1fr, auto, auto, auto),
    align: (left, left, left, right, right, right),
  )
]

== Load cases
#if basis.cases.len() > 0 {
  tbl(("Case", "Description"), basis.cases, columns: (auto, 1fr))
} else { empty[The analysis model has no static load cases.] }

#if "combinations" in basis [
  == Load combinations
  The strength design load combinations of the project settings (BNBC 2020 2.7.3); D includes
  the superimposed dead loads.
  #v(0.3em)
  #if basis.combinations.rows.len() > 0 {
    let cols = basis.combinations.columns
    tbl(
      ("Combination",) + cols,
      basis.combinations.rows,
      columns: (1fr,) + (auto,) * cols.len(),
      align: (left,) + (right,) * cols.len(),
    )
  } else { empty[There are no load combinations.] }
]

#if "modelling" in basis [
  == Analysis model and analyses
  #pairs(basis.modelling)
  Analyses run: #basis.analyses.join(", ").
]

// ───────────────────────────── soil and foundations ─────────────────────────────

#let soil = data.soil

#if soil.available [
  = Soil and foundations

  From the soil report of the project (1 Soil Report). Depths are below each borehole's
  ground level; levels in the project datum.

  == Soil report
  #pairs(soil.details)

  == Boreholes
  #tbl(
    ("Borehole", "X [m]", "Y [m]", "Ground level [m]", "Water table [m]", "Depth [m]", "Layers", "SPT", "Site class"),
    soil.boreholes,
    columns: (auto, auto, auto, auto, auto, auto, auto, auto, 1fr),
    align: (left, right, right, right, right, right, right, right, left),
    size: 8pt,
  )
  The water table is given as a depth below the borehole's ground level.

  #if soil.strata.len() > 0 [
    == Strata
    #tbl(
      ("Borehole", "Depth [m]", "Soil", "Description", "γ [kN/m³]", "cu [kPa]", "φ' [°]", "N60"),
      soil.strata,
      columns: (auto, auto, auto, 1fr, auto, auto, auto, auto),
      align: (left, left, left, left, right, right, right, right),
      size: 7.5pt,
    )
  ]

  == Site class
  #tbl(
    ("Borehole", "N̄", "s̄u [kPa]", "Class by N̄", "Class by s̄u", "Site class", "Over [m]"),
    soil.site.rows,
    columns: (auto, auto, auto, auto, auto, auto, 1fr),
    align: (left, right, right, center, center, center, left),
  )
  #bullets(soil.site.notes)
  #text(size: 8.5pt, fill: muted, soil.site.method)

  == Allowable bearing pressure
  Net allowable bearing pressure qa (kPa) of square footings, the lowest of the boreholes for
  each width B and founding depth Df (– where a borehole gives none). Factor of safety
  #soil.bearing.factorOfSafety on shear; allowable settlement #soil.bearing.allowableSettlement mm.
  Each footing's own qa (at its position, founding level, B and L) is in its bearing check.
  #v(0.3em)
  #let nd = soil.bearing.depths.len()
  #tbl(
    ("B",) + soil.bearing.depths,
    soil.bearing.rows,
    columns: (1fr,) + (auto,) * nd,
    align: (left,) + (right,) * nd,
  )
  #v(0.3em)
  The reference footing of each borehole, with its settlement and modulus of subgrade reaction:
  #tbl(
    ("Borehole", "B × Df [m]", "qa shear", "qa settlement", "qa [kPa]", "Governs", "Settlement [mm]", "ks [kN/m³]"),
    soil.bearing.reference,
    columns: (auto, auto, auto, auto, auto, 1fr, auto, auto),
    align: (left, left, right, right, right, left, right, right),
    size: 8pt,
  )
  #if soil.bearing.notes.len() > 0 { bullets(soil.bearing.notes, size: 8.5pt) }
  #text(size: 8.5pt, fill: muted, soil.bearing.method)

  == Liquefaction screening
  #tbl(
    ("Borehole", "Min. FS", "LPI", "Risk", "Liquefiable layers"),
    soil.liquefaction.rows,
    columns: (auto, auto, auto, auto, 1fr),
    align: (left, right, right, left, left),
    bad: soil.liquefaction.fails,
  )
  #if soil.liquefaction.notes.len() > 0 { bullets(soil.liquefaction.notes, size: 8.5pt) }
  #text(size: 8.5pt, fill: muted, soil.liquefaction.method)
]

// ───────────────────────────── foundations ─────────────────────────────

#let fdn = data.foundations

= Foundations

#if not fdn.available [
  #note(fdn.message)
] else [
  The foundations of 9 Substructure, designed for the support reactions of the analysis: the
  column bases are fixed supports of the analysis model. Bearing and pile loads are checked under
  the service combinations, the concrete (ACI 318-19) under the factored ones. Utilisation is
  demand over capacity; above 1.000 is marked FAIL.

  == Summary
  #pairs(fdn.summary, width: 40%)
  #if fdn.failed > 0 {
    note[*#fdn.failed foundation(s) or tie beam(s) fail their design checks.* They are
      highlighted below.]
  }

  == Governing checks
  #tbl(
    ("Id", "Type", "Columns", "Size", "Governing check", "Util.", "Combination", "Result"),
    fdn.rows,
    columns: (auto, auto, 1fr, auto, 1fr, auto, auto, auto),
    align: (left, left, left, left, left, right, left, center),
    bad: fdn.fails,
    size: 8pt,
  )

  #if fdn.pressures.len() > 0 [
    == Bearing pressure
    The largest net pressure under each footing and raft (the gross pressure less the overburden
    removed), against its net allowable bearing pressure qa.
    #v(0.3em)
    #tbl(
      ("Foundation", "Net pressure [kPa]", "qa [kPa]", "Combination", "qa from"),
      fdn.pressures,
      columns: (auto, auto, auto, 1fr, auto),
      align: (left, right, right, left, left),
    )
  ]

  #if fdn.capacities.len() > 0 [
    == Pile capacity
    Single-pile capacity at each pile cap (BNBC 2020 Part 6 Sec 3.10, geotechnical design of
    deep foundations): Qult = Qs + Qb - W, Qa the
    lesser of Qult / FS and the partial factors; Ta the allowable uplift.
    #v(0.3em)
    #tbl(
      ("Cap", "Pile", "Kind", "Borehole", "D [mm]", "L [m]", "Qs [kN]", "Qb [kN]", "Qult [kN]", "FS", "Qa [kN]", "Ta [kN]"),
      fdn.capacities,
      columns: (auto,) * 12,
      align: (left, left, left, left) + (right,) * 8,
      size: 7.5pt,
    )
    #for t in fdn.capacityTables [
      #v(0.4em)
      #text(size: 9pt, weight: "bold", t.title)
      #let nd = t.diameters.len()
      #tbl(
        ("Length",) + t.diameters,
        t.rows,
        columns: (1fr,) + (auto,) * nd,
        align: (left,) + (right,) * nd,
        size: 7.5pt,
      )
    ]
  ]

  #if fdn.pileLoads.len() > 0 [
    == Pile loads
    The load on each pile (cap/pile; u, v its offset from the cap's centre in mm): service loads
    against Qa, factored loads for the pile section. Negative values are tension.
    #v(0.3em)
    #tbl(
      ("Pile", "u", "v", "Service max [kN]", "Service min [kN]", "Factored max [kN]", "Factored min [kN]", "Qa [kN]"),
      fdn.pileLoads,
      columns: (auto,) * 8,
      align: (left,) + (right,) * 7,
      size: 8pt,
    )
  ]

  #if fdn.rafts.len() > 0 [
    == Rafts
    Plate on compression-only Winkler springs (modulus of subgrade reaction ks); settlements are
    net of the rebound of the excavation.
    #v(0.3em)
    #tbl(
      ("Raft", "ks [kN/m³]", "Mesh [mm]", "Net pressure [kPa]", "qa [kPa]", "Max contact [kPa]", "Max settlement [mm]", "Max differential [mm]", "Angular distortion [‰]"),
      fdn.rafts,
      columns: (auto,) * 9,
      align: (left,) + (right,) * 8,
      size: 7.5pt,
    )
  ]

  #if fdn.skipped.len() > 0 [
    == Foundations not designed
    #tbl(("Id", "Type", "Reason"), fdn.skipped, columns: (auto, auto, 1fr))
  ]

  == Checks of each foundation
  #for e in fdn.details {
    block(breakable: false, above: 1em, below: 0pt, {
      block(below: 0.4em, text(
        size: 9pt,
        weight: "bold",
        fill: if e.ok { ink } else { fail-ink },
        e.title,
      ))
      tbl(
        ("Check", "Demand", "Capacity", "Unit", "Util.", "Combination", "Result", "Note"),
        e.rows,
        columns: (20%, auto, auto, auto, auto, auto, auto, 1fr),
        align: (left, right, right, left, right, left, center, left),
        bad: e.fails,
        size: 7.5pt,
      )
    })
  }

  == Design method
  #bullets(fdn.method, size: 8.5pt)
  #if fdn.combinations.service.len() > 0 [
    Service combinations: #fdn.combinations.service.join(", "). \
    Strength combinations: #fdn.combinations.strength.join(", ").
  ]
]

// ───────────────────────────── 2 model ─────────────────────────────

= Analysis model

#let model = data.model

== Model summary
#pairs(model.rows)

#if model.derived.len() > 0 [
  == Equivalent static loads
  Values of the derivation of the analysis model from the building model and the project
  settings (BNBC 2020 6.2).
  #pairs(model.derived)
]

== Analysis run
#tbl(
  ("Case", "Analysis", "Steps", "Status"),
  model.run,
  columns: (1fr, auto, auto, auto),
  align: (left, left, right, left),
  bad: model.run.map(r => r.at(3) != "Complete"),
)
#if model.runWarnings.len() > 0 [
  Warnings of the run:
  #bullets(model.runWarnings)
]

// ───────────────────────────── 3 results ─────────────────────────────

= Analysis results

#let results = data.results

#if results.modal != none [
  == Modal periods and mass participation
  #let n = results.modal.columns.len()
  #tbl(results.modal.columns, results.modal.rows, align: (right,) * n)
]

== Base reactions
Sum of the support reactions of each load case, in global axes.
#v(0.3em)
#if results.reactions.len() > 0 {
  tbl(
    ("Load case", "ΣFx [kN]", "ΣFy [kN]", "ΣFz [kN]"),
    results.reactions,
    columns: (1fr, auto, auto, auto),
    align: (left, right, right, right),
  )
} else { empty[There are no static results.] }

#if results.displacements.len() > 0 [
  == Displacements and story drifts
  #tbl(
    ("Load case", "Max displacement [mm]", "Max story drift [%]", "Story", "Cd·δ/I [%]"),
    results.displacements,
    columns: (1fr, auto, auto, auto, auto),
    align: (left, right, right, left, right),
  )
]

#if results.notes.len() > 0 {
  bullets(results.notes, size: 8.5pt)
}

// ───────────────────────────── 4 member design ─────────────────────────────

= Member design

#let design = data.design

#if not design.available [
  #note[The member design checks could not be run: #design.problem]
] else [
  Design to #design.code. Forces are the factored combinations of the static load cases;
  utilisation is demand over design strength (φ applied). Elements whose utilisation exceeds
  1.000 are marked FAIL (utilisations are printed to three decimals, as checked).

  == Summary
  #pairs(design.summary, width: 40%)
  #if design.failed > 0 {
    note[*#design.failed element(s) fail their design checks.* They are highlighted in the
      tables below.]
  }

  #for t in design.tables [
    == #t.title
    #tbl(
      ("Element", "Type", "Governing check", "Demand", "Capacity", "Unit", "Util.", "Combination", "Result"),
      t.rows,
      columns: (auto, auto, 1fr, auto, auto, auto, auto, 1fr, auto),
      align: (left, left, left, right, right, left, right, left, center),
      bad: t.fails,
      size: 8pt,
    )
  ]

  #if design.skipped.len() > 0 [
    == Elements not designed
    #tbl(
      ("Element", "Kind", "Type", "Reason"),
      design.skipped,
      columns: (auto, auto, auto, 1fr),
    )
  ]

  == Design method
  #bullets(design.method)

  #if design.combinations.len() > 0 [
    Combinations checked: #design.combinations.join(", ").
  ]
]

// ───────────────────────────── MEP coordination ─────────────────────────────

#let mep = data.mep
#if mep.available [
  = MEP coordination

  The building services of 7 MEP against the structure: the equipment's loads in the analysis
  model, the sleeves and openings through beams, slabs and walls checked, and the clashes of the
  services' IFC models with the structure.

  == Summary
  #pairs(mep.summary, width: 40%)
  #if mep.failed > 0 {
    note[*#mep.failed sleeve(s) or opening(s) fail their checks.* They are highlighted below.]
  }
  #if mep.partial > 0 {
    note[*#mep.partial sleeve(s) or opening(s) are checked for their size and spacing only*:
      their shear and flexure (or punching) checks need the analysis results; run the analysis
      and write the report again.]
  }
  #if mep.open > 0 {
    note[*#mep.open hard clash(es) are not coordinated*: give each a sleeve or opening, or
      reroute the service.]
  }

  #if mep.equipment.len() > 0 [
    == Equipment loads
    Loads in kN by load case (SD the empty weight and plinth, F the contents, L any impact);
    pressure is the operating weight over the footprint [kPa].
    #tbl(
      ("Id", "Name", "Story", "On", "Loads [kN]", "Total [kN]", "Pressure"),
      mep.equipment,
      columns: (auto, 1fr, auto, auto, 1fr, auto, auto),
      align: (left, left, left, left, left, right, right),
      size: 8pt,
    )
  ]

  #if mep.openings.len() > 0 [
    == Sleeves and openings
    #tbl(
      ("Id", "Host", "Kind", "Governing check", "Util.", "Result"),
      mep.openings,
      columns: (auto, auto, 1fr, 1fr, auto, auto),
      align: (left, left, left, left, right, center),
      bad: mep.openingFails,
      size: 8pt,
    )
  ]

  #if mep.clashes.len() > 0 [
    == Clashes with the structure
    #tbl(
      ("Id", "Service", "Structure", "Kind", "Status", "Note"),
      mep.clashes,
      columns: (auto, 1fr, auto, auto, auto, 1fr),
      bad: mep.clashOpen,
      size: 8pt,
    )
  ]

  == Method
  #bullets(mep.method)
] else if mep.problem != "" [
  = MEP coordination
  #note[The MEP coordination could not be reported: #mep.problem]
]

// ───────────────────────────── 5 bill of quantities ─────────────────────────────

= Bill of quantities

#let boq = data.boq
#if boq.status != "ok" { note(boq.message) }
#if "groups" in boq and boq.groups.len() > 0 {
  for g in boq.groups [
    == #g.title
    #let rows = g.rows
    #let total = if g.total != "" { (("", "Total", g.total, g.unit),) } else { () }
    #tbl(
      ("Item", "Description", "Quantity", "Unit"),
      rows + total,
      columns: (auto, 1fr, auto, auto),
      align: (left, left, right, left),
    )
  ]
} else if boq.status == "ok" { empty[The bill of quantities has no items.] }

// ───────────────────────────── 6 limitations ─────────────────────────────

= Limitations and notes

These notes are printed as the analysis, design and quantity modules reported them. They state
what the software did not check or assumed; the engineer must consider each one.

#let lim = data.limitations

#if data.warnings.len() > 0 [
  == Warnings
  #bullets(data.warnings)
]

#if soil.available [
  == Soil and foundations
  #if lim.soil.len() > 0 { bullets(lim.soil) } else { empty[No notes.] }
]

== Foundations
#bullets(fdn.limits)
#if lim.foundations.len() > 0 { bullets(lim.foundations) }

== Member design
#if lim.design.len() > 0 { bullets(lim.design) } else { empty[No notes.] }

#if mep.available [
  == MEP coordination
  #if lim.mep.len() > 0 { bullets(lim.mep) } else { empty[No notes.] }
]

== Bill of quantities
#if lim.boq.len() > 0 { bullets(lim.boq) } else { empty[No notes.] }

== Analysis model
#if lim.model.len() > 0 { bullets(lim.model) } else { empty[No notes.] }
#if lim.run.len() > 0 [
  Warnings of the analysis run:
  #bullets(lim.run)
]

// ───────────────────────────── appendix ─────────────────────────────

#if design.available and design.details.len() > 0 [
  #set heading(numbering: "A.1")
  #counter(heading).update(0)
  = Appendix: design checks of every element

  Every check of every element, with the combination and position that govern it.

  #for e in design.details {
    // Each element's checks stay together with their title (a few rows each).
    block(breakable: false, above: 1em, below: 0pt, {
      block(below: 0.4em, text(
        size: 9pt,
        weight: "bold",
        fill: if e.ok { ink } else { fail-ink },
        e.title,
      ))
      tbl(
        ("Check", "Demand", "Capacity", "Unit", "Util.", "Combination", "Result", "Note"),
        e.rows,
        columns: (20%, auto, auto, auto, auto, auto, auto, 1fr),
        align: (left, right, right, left, right, left, center, left),
        bad: e.fails,
        size: 7.5pt,
      )
    })
  }
]
