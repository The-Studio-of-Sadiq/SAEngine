# Drawing sheets: layers, linetypes, text and plotting

The structural drawing sheets (`11 Exports/Drawings/S-1xx *.dxf`) use one layer scheme, one
text style and SAEngine's own linetypes, so that they open the same in AutoCAD, BricsCAD and
LibreCAD and plot as the PDF set does. The scheme is defined in
`python/src/saengine/drawings/sheets/layout.py` (`LAYERS`, `LINETYPES`, `FONT`,
`HATCH_SCALES`); the tests in `python/tests/test_drawings_cad.py` keep the sheets to it.

## Layers

Names follow the US National CAD Standard pattern that most Bangladeshi offices already use for
structural work (discipline `S-`, then the element). Colours are the AutoCAD Colour Index
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
| `S-DIMS` | 2 yellow | Continuous | 0.18 | Dimensions |
| `S-TEXT` | 7 | Continuous | 0.25 | Marks, labels, leaders, view titles |
| `S-TABLE` | 7 | Continuous | 0.25 | Schedules and tables (BBS, column schedule) |
| `S-VIEWPORT` | 8 | Continuous | 0.09 | The layout's viewport (not plotted) |

Bars are the heaviest lines of a detail (0.50) and concrete outlines lighter (0.35), as in RC
detailing practice: a reader sees the reinforcement first. A few entities override the
lineweight to draw lighter (blinding outline, mesh lines in a footing plan, wall section bars
0.13–0.18); the colour and linetype stay ByLayer.

Layer `0` holds nothing; `Defpoints` is the CAD programs' own.

## Linetypes

SAEngine defines its linetypes in each DXF (no `.lin` file is needed). Their dash and gap
lengths are paper millimetres (ISO 128 proportions) and the drawing's `LTSCALE` is the sheet's
base scale, so that they plot at these lengths whatever the scale:

| Linetype | Pattern (paper mm) | Used for |
| --- | --- | --- |
| `CENTER` | 12 dash, 3 gap, 2 dash, 3 gap | Grid lines |
| `DASHED` | 3 dash, 1.5 gap | Beams below, top bars in slab plans, slab line in beam elevations |
| `HIDDEN` | 2 dash, 1 gap | Foundations below the level |
| `PHANTOM` | 12, 2, 2, 2, 2, 2 | Not used by the sheets; for the engineer's own additions |

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

## Floor plan exports

The per-storey floor plans (`11 Exports/Floor Plan/<story>.dxf`, `saengine export --format
dxf`) are real-size plans without a sheet, drawn as the app's floor plan editor draws them, on
their own layers (`S-GRID`, `S-GRID-IDEN`, `S-COLS`, `S-BEAM`, `S-WALL`, `S-SLAB`, `S-FNDN`,
`S-ANNO-IDEN`). They follow the same rules for CAD programs: one text style (`Standard`,
Arial) and only the linetypes their layers use (`CENTER`, `DASHED`, ezdxf's definitions, which
the entities' own linetype scales of 200 and 100 are made for).

The frame follows ISO 5457: 20 mm binding margin on the left, 10 mm elsewhere, centring marks,
the title block in a strip at the right. Nothing but the frame lies outside the border.
