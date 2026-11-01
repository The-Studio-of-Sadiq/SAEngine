# Drawing sheets: layers, linetypes, text and plotting

The drawing sheets (`11 Exports/Drawings/S-1xx *.dxf`, `A-1xx *.dxf` when the project has
an architecture, and `P-`, `M-`, `E-`, `FP-` and `MC-` sheets when it has building services in
07 MEP) use one layer scheme, one
text style and SAEngine's own linetypes, so that they open the same in AutoCAD, BricsCAD and
LibreCAD and plot as the PDF set does. The scheme is defined in
`python/src/saengine/drawings/sheets/layout.py` (`LAYERS`, `LINETYPES`, `FONT`,
`HATCH_SCALES`); the tests in `python/tests/test_drawings_cad.py` keep the sheets to it.

## Layers

Names follow the US National CAD Standard pattern that most Bangladeshi offices already use for
structural work (discipline `S-`, then the element; `A-` for the architectural sheets, which use
the `S-` grid, dimension, text and table layers too, and draw the structure they show on its
`S-` layers). Colours are the AutoCAD Colour Index
(ACI); the lineweight is the layer's plotted lineweight. Every entity is ByLayer (colour,
linetype and lineweight), except the north arrow's solid fill.

| Layer | Colour | Linetype | Lineweight (mm) | Holds |
| --- | --- | --- | --- | --- |
| `S-SHEET` | 7 white/black | Continuous | 0.50 (trim line 0.13) | Sheet frame, border, centring marks |
| `S-TITLE` | 7 | Continuous | 0.25 | Title block lines and text, north arrow |
| `S-GRID` | 1 red | `CENTER` | 0.18 | Grid lines |
| `S-GRID-BUBBLE` | 7 | Continuous | 0.25 | Grid bubbles and their labels |
| `S-COLS` | 7 | Continuous | 0.50 | Columns (plan outline, elevation break lines) |
| `S-BEAM` | 3 green | `DASHED` | 0.35 | Beams below the slab, in plans |
| `S-BEAM-EDGE` | 3 | Continuous | 0.35 | Beam outlines in elevations and sections |
| `S-SLAB` | 7 | Continuous | 0.35 | Slab edges |
| `S-OPEN` | 7 | Continuous | 0.25 | Openings (with their cross) |
| `S-WALL` | 7 | Continuous | 0.50 | Walls |
| `S-STAIR` | 6 magenta | Continuous | 0.25 | Stairs: flights, treads, walking line |
| `S-FNDN` | 4 cyan | `HIDDEN` | 0.35 | Footings, pile caps and piles below the level |
| `S-CONC` | 7 | Continuous | 0.35 | Concrete outlines of details and sections |
| `S-HATCH` | 8 grey | Continuous | 0.09 | Hatching of cut concrete, blinding |
| `S-REBAR-MAIN` | 1 red | Continuous | 0.50 | Main bars (lines and dots in section) |
| `S-REBAR-LINK` | 5 blue | Continuous | 0.25 | Links, ties, stirrups, wall hoops |
| `S-STEEL` | 30 orange | Continuous | 0.50 | Structural steel members (plans, elevations, details) |
| `S-STEEL-AXIS` | 30 | `CENTER` | 0.18 | Steel members' work lines (centre lines) |
| `S-STEEL-PLATE` | 4 cyan | Continuous | 0.35 | Connection plates: gussets, tabs, fin and end plates; the Whitmore section (dashed) |
| `S-BOLT` | 1 red | Continuous | 0.25 | Bolts, drawn as their holes with a cross |
| `S-WELD` | 6 magenta | Continuous | 0.25 | Weld symbols (AWS A2.4) and their text |
| `S-DIMS` | 2 yellow | Continuous | 0.18 | Dimensions |
| `S-TEXT` | 7 | Continuous | 0.25 | Marks, labels, leaders, view titles |
| `S-TABLE` | 7 | Continuous | 0.25 | Schedules and tables (BBS, column schedule, door and window and room finish schedules) |
| `A-WALL` | 7 | Continuous | 0.50 | Architectural walls cut by a plan (their outline, stopped at columns and openings) |
| `A-WALL-PATT` | 8 grey | Continuous | 0.09 | Wall layer lines and their hatching (masonry ANSI31, concrete AR-CONC) |
| `A-DOOR` | 3 green | Continuous | 0.25 | Doors: jambs, leaves and swings in plan; outlines in elevation |
| `A-GLAZ` | 4 cyan | Continuous | 0.25 | Windows: frame and glass (`HIDDEN` above the plan's cut) |
| `A-AREA-IDEN` | 7 | Continuous | 0.25 | Room tags: number and name, net area, finish codes |
| `A-ELEV` | 7 | Continuous | 0.25 | Elevations and sections: what is seen beyond the cut |
| `A-SECT` | 7 | Continuous | 0.50 | Sections: outlines of what the cut passes through; the ground line |
| `A-ANNO-SYMB` | 7 | Continuous | 0.25 | Section lines (`PHANTOM`) and their marks on the plans |
| `P-DOMW` | 5 blue | Continuous | 0.35 | Plumbing: cold and hot water risers, pump mains |
| `P-SANR` | 3 green | Continuous | 0.35 | Plumbing: soil, waste and vent stacks |
| `P-STRM` | 4 cyan | Continuous | 0.35 | Plumbing: rainwater leaders and roof drains |
| `P-EQPM` | 5 | Continuous | 0.35 | Plumbing: tanks, reservoirs, septic tanks, soak wells; wet rooms |
| `M-DUCT` | 30 orange | Continuous | 0.35 | HVAC ducts (both edges) and duct risers |
| `M-EQPM` | 3 | Continuous | 0.35 | HVAC plant and other equipment |
| `E-CABL` | 2 yellow | Continuous | 0.35 | Electrical: cable trays, busbar and cable risers |
| `E-EQPM` | 1 red | Continuous | 0.35 | Electrical: equipment, electrical rooms, air terminals |
| `F-PROT` | 1 | Continuous | 0.35 | Fire protection: risers and mains |
| `F-EQPM` | 1 | Continuous | 0.35 | Fire protection: pumps, tanks, the pump room |
| `M-SHFT` | 8 grey | `PHANTOM` | 0.25 | Service shafts |
| `M-SLEV` | 6 magenta | Continuous | 0.25 | Sleeves and openings for services (with a cross) |
| `M-ANNO` | 7 | Continuous | 0.25 | MEP tags: marks, sizes, systems |
| `S-REV` | 6 | Continuous | 0.35 | Revision clouds and their triangles (drawn again on each run) |
| `S-VIEWPORT` | 8 | Continuous | 0.09 | The layout's viewport (not plotted) |

Bars are the heaviest lines of a detail (0.50) and concrete outlines lighter (0.35), as in RC
detailing practice: a reader sees the reinforcement first. A few entities override the
lineweight to draw lighter (blinding outline, mesh lines in a footing plan, wall section bars
0.13–0.18); the colour and linetype stay ByLayer.

Layer `0` holds nothing; `Defpoints` is the CAD programs' own.

**Office standard.** Project Settings → Drawings → Office standard renames these layers (a
prefix for all, or a name per layer), sets their colours and lineweights, the font of `SAE` and
`Standard` (Arial, Arial Narrow, Calibri, Segoe UI or Tahoma) and the arrows of the dimension
styles (tick, closed, dot, oblique) (`drawings/sheets/standards.py`). The sheets are drawn on
the names above and renamed only when written; `drawings.json` keeps the names used
(`layerNames`), so that the next generation names an earlier sheet's layers back before it
looks for your own edits. An office name must not be a name of this table, nor given twice.

## Linetypes

SAEngine defines its linetypes in each DXF (no `.lin` file is needed). Their dash and gap
lengths are paper millimetres (ISO 128 proportions) and the drawing's `LTSCALE` is the sheet's
base scale, so that they plot at these lengths whatever the scale:

| Linetype | Pattern (paper mm) | Used for |
| --- | --- | --- |
| `CENTER` | 12 dash, 3 gap, 2 dash, 3 gap | Grid lines |
| `DASHED` | 3 dash, 1.5 gap | Beams below, top bars in slab plans, slab line in beam elevations |
| `HIDDEN` | 2 dash, 1 gap | Foundations below the level; windows above the cut of an architectural plan |
| `PHANTOM` | 12, 2, 2, 2, 2, 2 | Section lines on the architectural plans |

`PSLTSCALE` is 0: the sheets are drafted in model space at the base scale (see below), and the
layout's single viewport shows them at that scale, so the model space `LTSCALE` applies.

## Text

One text style, `SAE`, with the TrueType font **Arial** (`arial.ttf`, family `Arial`): every
Windows has it, AutoCAD and BricsCAD draw it as the PDF does, and the label placement measures
text with its widths. `Standard` uses the same font, so that text the engineer adds matches.
No SHX font is referenced (those belong to the CAD programs and differ between them).
LibreCAD reads no TrueType fonts and draws its own default font instead; its letters are a
little narrower, so the text still fits its boxes.

Text heights on paper, the ISO 3098 series:

| Height | Used for |
| --- | --- |
| 2.5 mm | Labels, bar marks, dimensions, table cells, notes |
| 3.5 mm | Title block values, the notes' heading, north arrow "N" |
| 5.0 mm | View titles, the drawing title, the firm's name |
| 7.0 mm | Sheet number and revision |

The model space text height is the paper height times the sheet's base scale ( `$TEXTSIZE` is
set to 2.5 mm on paper for new text).

## Dimensions

One dimension style per sheet, `SAE-<N>` for the base scale 1:N: text 2.5 mm in style `SAE`,
architectural ticks 2 mm, `DIMSCALE` N, text above the line, no trailing zeros. A view at
another scale 1:M on the same sheet (a beam section at 1:25 on a 1:50 sheet) uses the copy
`SAE-<N>-<M>`, whose linear factor (`DIMLFAC` M/N) makes it read real millimetres. No
dimension carries overrides, so editing a dimension in AutoCAD keeps its look.

## Hatches

Hatch patterns are ezdxf's metric definitions, written into each HATCH (no `.pat` file is
needed), ByLayer, on `S-HATCH`:

| Pattern | Scale (per unit of the base scale) | Looks like on paper |
| --- | --- | --- |
| `ANSI31` | 1.6 / 3.175 | 45° lines 1.6 mm apart: cut columns and walls in plans, wall sections |
| `AR-CONC` | 0.05 | Concrete specks of about 1 mm: blinding under footings |
| `SOLID` | – | Bars in section (with the bar's circle) |

## Sheets, layouts and plotting

Each sheet is drafted in model space at its base scale 1:N (the frame and title block N times
paper size; plans at 1:100 and elevations at 1:50 at real size in millimetres), with a paper
space layout named after the sheet number holding one viewport of the whole sheet at 1:N.
The layout's page setup is AutoCAD's `DWG To PDF.pc3`, paper `ISO full bleed A1/A2/A3`, scale
1:1, plot style table `monochrome.ctb`: in AutoCAD, open the layout tab and plot, or publish
all sheets, and the result matches `drawings.pdf`. In LibreCAD (model space only), print the
model space at 1:N on the sheet's size. A program without that plotter falls back to its own
default device and keeps the paper size and scale.

## Your edits, revisions and issue

**Your edits are kept.** Draw on a sheet's DXF in LibreCAD or AutoCAD (a note, an extra
dimension, a stamp, a sketch) and save it as DXF under the same name: when the sheet is drawn
again, everything SAEngine did not draw is copied into the new sheet. SAEngine knows what it drew
from `.sheet-index/<sheet>.json.gz` beside the sheets (keep that folder). Entities SAEngine draws
are always drawn afresh from the model, so change the model, not SAEngine's own lines, to change
them. Put your additions on a layer of your own (not an `S-` or `A-` layer of the table above):
they are then kept even when a CAD program rewrote the whole file on saving, or when the sheet
was drawn by an older SAEngine without an index. Layer `S-REV` is SAEngine's and is never kept.

**Issue Drawings** (11 Exports, Drawings) draws every sheet again and gives each sheet that is new
or changed since its last issue the issue's revision (default: the one after the last issue, `0`
→ `1`, `A` → `B`, `P1` → `P2`): its title block REV and revision table list that sheet's own
issues. The issued DXFs, the PDF set, the register and (when asked) the DWGs are copied into
`Issued/<rev> <date>/`, with what each sheet showed when issued. From then on, a generation
compares each sheet's drawing area with its last issue and draws a revision cloud with the
pending revision's triangle around each group of changes (layer `S-REV`; a sheet changed nearly
everywhere is listed as revised throughout instead). The clouds of earlier revisions are not
drawn again.

**The drawing register** (`register.pdf`, `register.csv`, `register.json`) lists every sheet
with its revision at each issue, then the issues with their dates, purposes and descriptions.
Until the first issue the title blocks show the revisions of Project Settings > Drawings.

**DWG.** The sheets are DXF; **Export DWG** (or *Also write DWG* when issuing) writes them as
AutoCAD R2000 DWG into `DWG/` with `dxf2dwg` of GNU LibreDWG, the setup's optional DWG component
(GPL-3.0, run as a separate program, never linked into SAEngine). Without it the sheets stay DXF
only. The DXF remains the master: LibreDWG's DWG writer is younger than its reader.

## Structural steel sheets

When the project has structural steel members (object types whose material is a steel of
03 Materials), the set gets steel sheets after the concrete ones (`drawings/sheets/steel.py`):
steel general notes with the steel items of the bill of quantities and a bolt list; a steel
framing plan per level (steel beams as heavy single lines, braces below the level dashed,
concrete members for reference); an elevation per braced plane (a grid line, or the brace's
own plane); the steel member schedule; the connection details at 1:5 (1:10 when a detail does
not fit the sheet).

- Masses are the bill of quantities' (`10 BOQ/boq.json`, per member from its breakdown), so
  the schedule's total is the BOQ's steel total; a bill older than 06 BIM, 04 Objects or
  03 Materials is measured again in memory by the BOQ module, and the problems say so.
- Connections are the designed ones of the object types (`connection` of 04 Objects, checked
  by `design/steel_connections.py`): bolts, pitch, gauge, end and edge distances, plates and
  welds as given there; the Whitmore width is the design module's, drawn at the bolt row
  deepest in the gusset with the 30° spread from the row nearest the brace. The tab clearance
  to the frame (50 mm) and the brace setback (50 mm) are drafting values, noted on the sheet.
- Weld symbols follow **AWS A2.4**: the arrow, the reference line, the fillet triangle with
  its perpendicular leg on the left (below the line: arrow side, above: other side, both: both
  sides), the leg size left of it, the length right of it, notes in the tail.
- Bolts are drawn as their holes with a cross; the bolt circles carry their row and line as
  XDATA (`SAENGINE`), the steel lines their member mark and section.

## Floor plan exports

The per-storey floor plans (`11 Exports/Floor Plan/<story>.dxf`, `saengine export --format
dxf`) are real-size plans without a sheet, drawn as the app's floor plan editor draws them, on
their own layers (`S-GRID`, `S-GRID-IDEN`, `S-COLS`, `S-BEAM`, `S-WALL`, `S-SLAB`, `S-FNDN`,
`S-ANNO-IDEN`). They follow the same rules for CAD programs: one text style (`Standard`,
Arial) and only the linetypes their layers use (`CENTER`, `DASHED`, ezdxf's definitions, which
the entities' own linetype scales of 200 and 100 are made for).

The frame follows ISO 5457: 20 mm binding margin on the left, 10 mm elsewhere, centring marks,
the title block in a strip at the right. Nothing but the frame lies outside the border.

## 3D reinforcement cages and bar congestion

**Reinforcement** in the Building Model's 3D view (06 BIM) shows the designed bars of the beams
and columns: the bars, marks, lengths, hooks and hoop rows of the detailing the sheets are drawn
from, placed on the design's own section layout (the bars the design checks used, corners first).
Hide Columns and Beams in the legend to see the cages. While it is on, Export IFC writes them too,
as IfcReinforcingBar (one per bar mark of a member, a swept disk along each bar's centreline,
NominalDiameter, CrossSectionArea, BarLength, MAIN or LIGATURE, Tag = the mark). Slabs, walls,
stairs and foundations are not drawn in 3D yet.

Every drawing generation checks bar congestion and writes `rebar-congestion.csv` beside the
sheets; the failing checks are among the drawings' warnings:

| Check | Limit | Clause |
| --- | --- | --- |
| Bars of a layer of a beam | max(db, 25 mm) clear | BNBC 2020 Part 6 Sec 8.1.6.1, p. 1068 |
| Between layers | 25 mm clear | Sec 8.1.6.2, p. 1068 |
| Column bars | max(1.5 db, 40 mm) clear | Sec 8.1.6.3, p. 1068 |
| Beam bars past the column bars at a joint | a clash fails; less than the 8.1.6.1 spacing is tight | practice (BNBC gives no figure for crossing bars) |
| Top (bottom) bars of beams from two directions | they cannot share a level: one set a bar diameter lower (higher) | practice |

The limits are the code pack's (`detailing.spacing`); a pack without them skips the check.
