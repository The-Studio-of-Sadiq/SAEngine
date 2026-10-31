// SAEngine design report (Part 11 Exports). Copyright (c) SAEngine contributors.
// Licensed under the AGPL-3.0-only license.
//
// Draws the report document of saengine.report.document.report_document, passed as JSON in
// sys.inputs.data: the cover, the contents and each section's blocks. The chapters are laid out
// in Python (the Word file draws the same document); this file only knows the kinds of block.
// Every value arrives as a string and is printed as text: user text needs no escaping here.

#let doc = json(bytes(sys.inputs.at("data")))
#let meta = doc.meta
#let cover = doc.cover
#let letterhead = doc.letterhead

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

// The letterhead: the logo and the organisation's name and lines, on every page.
#let letterhead-block(size: 8pt) = {
  if letterhead.enabled and (letterhead.organisation != "" or letterhead.logo != "") {
    grid(
      columns: (auto, 1fr),
      column-gutter: 6pt,
      align: horizon,
      if letterhead.logo != "" { image(letterhead.logo, height: 9mm) } else { [] },
      {
        set text(size: size)
        if letterhead.organisation != "" { text(weight: "bold", letterhead.organisation) }
        for line in letterhead.lines { linebreak(); text(fill: muted, line) }
      },
    )
  }
}

// Pages after the cover carry the header and footer; without a cover, every page does.
#let first-page = if cover.show { 2 } else { 1 }

#set page(
  paper: doc.paper,
  margin: (left: 20mm, right: 18mm, top: if letterhead.enabled { 30mm } else { 24mm }, bottom: 22mm),
  header: context {
    if counter(page).get().first() >= first-page {
      set text(size: 8pt, fill: muted)
      if letterhead.enabled {
        letterhead-block(size: 7.5pt)
        v(-0.2em)
      }
      grid(
        columns: (1fr, auto),
        meta.project, meta.title,
      )
      v(-0.4em)
      line(length: 100%, stroke: 0.4pt + rule)
    }
  },
  footer: context {
    if counter(page).get().first() >= first-page {
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

// ───────────────────────────── blocks ─────────────────────────────

#let aligns-of(codes) = codes.map(c => if c == "r" { right } else if c == "c" { center } else { left })
#let columns-of(specs) = specs.map(c => {
  if c == "auto" { auto } else if c.ends-with("fr") { float(c.slice(0, -2)) * 1fr } else if c.ends-with("%") { float(c.slice(0, -1)) * 1% } else { auto }
})

// A table of strings; `bad`: per row, true to highlight it as a failure.
#let tbl(b) = {
  let head = b.head
  let aligns = aligns-of(b.align)
  let bad = b.at("bad", default: none)
  set text(size: b.size * 1pt)
  set par(justify: false)
  table(
    columns: columns-of(b.columns),
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
    ..b.rows.enumerate().map(((i, row)) => {
      let failing = bad != none and bad.at(i, default: false)
      row.map(cell => if failing and (cell == "FAIL") {
        text(weight: "bold", fill: fail-ink, cell)
      } else { cell })
    }).flatten(),
  )
}

// Label/value pairs as a two-column table without a header.
#let pairs(rows, width) = {
  set text(size: 9pt)
  set par(justify: false)
  table(
    columns: (float(width.slice(0, -1)) * 1%, 1fr),
    inset: (x: 4pt, y: 3pt),
    stroke: (x, y) => (bottom: 0.3pt + rule),
    ..rows.map(((label, value)) => (text(fill: muted, label), value)).flatten(),
  )
}

#let note(strong, body) = block(
  width: 100%,
  inset: (x: 8pt, y: 6pt),
  fill: warn-fill,
  radius: 2pt,
  text(size: 9pt, {
    if strong != "" { text(weight: "bold", strong) + " " }
    body
  }),
)

// The checks of one element or foundation. The table breaks across pages with its header
// repeated, the title stays with its first rows, and each note is printed on a row of its own
// under its check, the full width of the table, so it never squeezes the columns.
#let checks-table(e) = {
  block(above: 1.1em, below: 0.4em, sticky: true, text(
    size: 9pt,
    weight: "bold",
    fill: if e.ok { ink } else { fail-ink },
    e.title,
  ))
  set text(size: 7.5pt)
  set par(justify: false)
  let cells = ()
  let fills = ()
  for (i, row) in e.rows.enumerate() {
    let failing = e.fails.at(i, default: false)
    let fill = if failing { fail-fill } else { none }
    let result = row.at(6)
    if i > 0 { cells.push(table.hline(stroke: 0.3pt + rule)) }
    cells += row.slice(0, 6) + (
      if failing { text(weight: "bold", fill: fail-ink, result) } else { result },
    )
    fills.push(fill)
    let remark = row.at(7, default: "")
    if remark != "" {
      cells.push(table.cell(colspan: 7, inset: (left: 12pt, right: 4pt, top: 0pt, bottom: 3.2pt),
        text(fill: muted, remark)))
      fills.push(fill)
    }
  }
  table(
    columns: (1fr, auto, auto, auto, auto, columns-of((e.combination,)).at(0), auto),
    align: (x, y) => (left, right, right, left, right, left, center).at(x) + horizon,
    inset: (x: 4pt, y: 3.2pt),
    stroke: (x, y) => (
      top: if y == 0 { 0.8pt + ink } else { none },
      bottom: if y == 0 { 0.6pt + ink } else { none },
    ),
    fill: (x, y) => if y == 0 { head-fill } else { fills.at(y - 1, default: none) },
    table.header(..("Check", "Demand", "Capacity", "Unit", "Util.", "Combination", "Result")
      .map(h => text(weight: "bold", h))),
    ..cells,
    table.hline(stroke: 0.6pt + ink),
  )
}

#let render(b) = {
  let t = b.t
  if t == "h" {
    heading(level: b.level, b.text)
  } else if t == "p" {
    let body = {
      if b.at("strong", default: "") != "" { text(weight: "bold", b.strong) + " " }
      b.text
    }
    let size = b.at("size", default: none)
    let fill = if b.at("muted", default: false) { muted } else { ink }
    par(if size != none { text(size: size * 1pt, fill: fill, body) } else { text(fill: fill, body) })
  } else if t == "pairs" {
    pairs(b.rows, b.width)
  } else if t == "table" {
    tbl(b)
  } else if t == "checks" {
    checks-table(b)
  } else if t == "bullets" {
    set text(size: b.size * 1pt)
    set par(justify: false)
    for item in b.items [- #item]
  } else if t == "note" {
    note(b.at("strong", default: ""), b.text)
  } else if t == "empty" {
    text(size: 9pt, style: "italic", fill: muted, b.text)
  } else if t == "label" {
    let tone = b.at("tone", default: none)
    block(above: 8pt, below: 4pt, sticky: true, text(
      size: 9pt,
      weight: if tone == "muted" { "regular" } else { "bold" },
      fill: if tone == "fail" { fail-ink } else if tone == "muted" { muted } else { ink },
      b.text,
    ))
  }
}

#let section(s) = {
  heading(level: 1, s.title)
  for b in s.blocks { render(b) }
}

// ───────────────────────────── cover ─────────────────────────────

#if cover.show {
  page(header: none, footer: none, margin: (x: 25mm, top: if letterhead.enabled { 22mm } else { 40mm }, bottom: 25mm))[
    #set par(justify: false)
    #if letterhead.enabled {
      letterhead-block(size: 9pt)
      v(12mm)
    }
    #text(size: 10pt, fill: muted, tracking: 0.08em, upper(cover.title))
    #v(6mm)
    #text(size: 24pt, weight: "bold", meta.project)
    #if cover.subtitle != "" {
      v(2mm)
      text(size: 13pt, fill: muted, cover.subtitle)
    }
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
    #v(8mm)
    // The design result first: a report whose members fail must say so on its cover.
    #let status = doc.status
    #if cover.status {
      block(
        width: 100%,
        inset: (x: 10pt, y: 9pt),
        radius: 2pt,
        fill: if status.state == "fail" { fail-fill } else if status.state == "pass" { rgb("#dcefdc") } else { warn-fill },
        stroke: 0.8pt + (if status.state == "fail" { fail-ink } else if status.state == "pass" { rgb("#2e6b30") } else { rgb("#9a6b00") }),
        text(
          size: 11pt,
          weight: "bold",
          fill: if status.state == "fail" { fail-ink } else if status.state == "pass" { rgb("#1f4d21") } else { ink },
          status.headline,
        ),
      )
    }
    #v(1fr)
    #let sign = meta.at("titleBlock", default: ())
    #if cover.titleBlock and sign.len() > 0 {
      set text(size: 9pt)
      table(
        columns: (1fr, 1fr, 1fr, 1fr),
        stroke: 0.5pt + rule,
        inset: (x: 5pt, y: 4pt),
        ..sign.map(((label, value)) => (
          table.cell(stack(spacing: 3pt, text(size: 7.5pt, fill: muted, label), if value == "" { v(9pt) } else { value })),
        )).flatten(),
        ..range(calc.rem(4 - calc.rem(sign.len(), 4), 4)).map(_ => []),
      )
      v(4mm)
    }
    #if doc.warnings.len() > 0 {
      note("Read before use.", "This report carries " + str(doc.warnings.len()) + " warning(s), listed in the Limitations section.")
      v(6mm)
    }
    #if cover.note != "" {
      text(size: 9.5pt, cover.note)
      v(4mm)
    }
    #set text(size: 9pt, fill: muted)
    Prepared with SAEngine #meta.version (AGPL-3.0), typeset with Typst. \
    #meta.units
    #v(3mm)
    This report presents the results of computer analysis and design. It shall be reviewed,
    checked and signed by the structural engineer responsible for the design.
  ]
}

#counter(page).update(if cover.show { 2 } else { 1 })
#if doc.contents {
  outline(title: [Contents], depth: 2, indent: auto)
}

// ───────────────────────────── sections ─────────────────────────────

#for s in doc.sections.filter(s => not s.landscape) { section(s) }

// The appendix: landscape, so the wide check tables (combination, notes) read on one line per
// check; numbered A, A.1.
#let appendix = doc.sections.filter(s => s.landscape)
#if appendix.len() > 0 [
  #set page(flipped: true)
  #set heading(numbering: "A.1")
  #counter(heading).update(0)
  #for s in appendix { section(s) }
]
