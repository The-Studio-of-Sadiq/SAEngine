# Part 11: Exports

Part 11 is what the project hands over: the design report, the structural drawings, the building
model as IFC, the floor plans as DXF, the bill of quantities as CSV, and the project archive.
Everything is written to the `11 Exports` folder.

Open it with **11 Exports** in the sidebar (or *SAEngine: Exports*).

![The Exports page](images/exports.png)

## The Exports page

| Row | Make it with | Writes |
| --- | --- | --- |
| **Design report** — the printed calculations: loads, analysis, design checks and their limitations | **Print Design Report** / **Update Report** | `11 Exports/report.pdf` |
| **IFC building model** — for BIM software | **Export IFC** | `11 Exports/IFC/<project>.ifc` |
| **DXF floor plans** — the structural plan of every storey, for CAD | **Export DXF Floor Plans** | `11 Exports/Floor Plan/` |
| **Bill of quantities (CSV)** | **Export CSV...** | `11 Exports/boq.csv` |
| **Structural drawings** | **Generate Drawings** | `11 Exports/Drawings/` |
| **Project archive (.civil)** | **Export Project (.civil)...** | where you save it |

A row that cannot be made yet says what is missing (*Build the building model (6 BIM) first.*,
*Measure the bill of quantities (10 BOQ) first.*). Each file has **Open**, **Reveal in File
Explorer** and, for DXF, **Open in LibreCAD**. The toolbar has **Open Exports Folder**.

## The design report

**Print Design Report** (Exports page, File menu, or Command Palette) typesets the report as a
PDF with Typst and opens it: *Design report written (48 pages).* Warnings are listed in the
report's *Limitations* section. It needs the analysis results (*There are no analysis results:
run the analysis first.*). Run All rewrites it every time.

Contents:

1. **Design basis:** codes and method, building and site, seismic force-resisting system,
   materials, area loads, load cases, load combinations, analysis model and analyses.
2. **Soil and foundations** (with boreholes) and **Foundations**.
3. **Analysis model:** model summary, analysis run.
4. **Analysis results:** modal periods and mass participation, base reactions per case,
   displacements and storey drifts, earthquake design from the response spectrum (scaling,
   torsion, design drift), section stiffness and second-order effects.
5. **Member design.**
6. **Bill of quantities.**
7. **Limitations and notes.**
8. **Appendix:** the design checks of every element.

## Structural drawings

The **Structural drawings** section of the Exports page makes the drawing set: *framing plans,
column and beam schedules, slab, footing, wall and stair details with a title block, as DXF for
LibreCAD and one PDF set, with the bar bending schedule.*

![The drawings on the Exports page](images/drawings.png)

1. Fill in the **Title block and sheets** (Firm, Engineer, Checked by, Approved by, Project
   number, Revision, Sheet size, Scales) with **Edit in Project Settings** (Project Settings →
   Drawings).
2. Choose the **sheet size** (A1, A2 or A3; default A1).
3. Click **Generate Drawings**. SAEngine runs the design checks, details the reinforcement, makes
   the bar bending schedule, draws the sheets and writes DXF, PDF and previews (about 15 s for the
   sample, minutes for a large building).
4. The sheet list shows each sheet (number, title, size, *Current* or *Out of date —
   regenerate*) with a thumbnail, **Preview**, **Open in LibreCAD** and **Reveal in File
   Explorer**. **Open PDF Set** and **Bar Bending Schedule (CSV)** open the whole set.

Sheets are numbered from **S-101** in this order: general notes, foundation plan, framing plans
(one per level), slab reinforcement plans, column schedule, beam elevations, foundation details,
wall details, stair details, bar bending schedule. A plan that does not fit its scale is drawn at
the next scale (*drawn at 1:150, 1:100 does not fit*). Every plan notes *Levels are top of slab.*

If design checks fail or bars cannot be detailed, the general notes sheet says **NOT FOR
CONSTRUCTION until these are resolved: ...**. Fix the design first.

Run All regenerates the drawings when a set exists and is out of date; **the first set is always
started here**.

![A sheet in the drawing preview](images/drawing-preview.png)

**Preview** opens the sheet in SAEngine (**Zoom In**, **Zoom Out**, **Fit Sheet**, **Actual
Pixels**, **Open in LibreCAD**, **Open PDF Set**).

Files in `11 Exports/Drawings/`: one DXF per sheet (`S-101 General notes.dxf`, ...),
`drawings.pdf`, `previews/*.png`, `bbs.csv` (UTF-8 with BOM, for Excel) and `drawings.json`.

### Opening the DXF sheets in CAD

The sheet DXFs are written for AutoCAD, BricsCAD and LibreCAD: layers follow the US National CAD
Standard pattern (`S-GRID`, `S-COLS`, `S-BEAM`, ...), text uses Arial, and each sheet plots
from model space and from its layout (see [docs/drawings-layers.md](../drawings-layers.md) and,
for checking them in AutoCAD, [docs/drawings-qa.md](../drawings-qa.md)). **Open in LibreCAD**
opens a sheet in the LibreCAD bundled with SAEngine (or the program in the setting
`saengine.cad.program`). **Open DXF in CAD...** (File menu) opens any DXF. DXF files also open inside SAEngine
in a read-only CAD Drawing Editor.

### Bar bending schedule

`bbs.csv` lists member, bar mark, type and size, BS 8666 shape code, dimensions, number, cutting
length (rounded up to 25 mm), total length and mass, with totals per bar size.

## DXF floor plans and IFC

- **Export DXF Floor Plans** writes one DXF per storey with layers S-GRID, S-COLS, S-BEAM and
  others (also **Export DXF** in the floor plan).
- **Export IFC** writes the building model (elements, storeys, materials) as IFC.

## Not confirmed / limitations

- The BS 8666 shape-code values in the bar bending schedule are marked in the code as *to be
  checked against BS 8666:2020 before the schedules are issued for fabrication*.
- Whether rafts and tie beams are drawn on the foundation plan was not confirmed.
