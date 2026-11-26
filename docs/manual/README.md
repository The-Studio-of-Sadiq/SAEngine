# SAEngine User Manual

SAEngine version 0.0.52 (Alpha 3) and the builds after it. This manual describes what the
program does, part by part, with four step-by-step tutorials. It is written for practising
structural engineers who know their design code and programs such as ETABS and AutoCAD. The
[glossary](glossary.md) maps SAEngine's terms to theirs.

The same content is compiled into one PDF, **SAEngine User Manual**
([SAEngine-User-Manual.pdf](SAEngine-User-Manual.pdf)), by [build.py](build.py).

> **Alpha.** SAEngine is under active development. Check its results independently before
> using them for construction. Every chapter ends with a list of what is limited or could not be
> confirmed in this version.

## Contents

**Getting started**

- [Getting started](00-getting-started.md) — the Start page, the New Project wizard, the window
  (ribbon, stage bar, model view, Properties, Tables), Run All, versions, co-editing, settings

**The eleven parts**

1. [Soil Report](01-soil-report.md) — boreholes, SPT, lab tests, site class, bearing, site map
2. [Project Settings](02-project-settings.md) — code pack, site, loads, load patterns,
   combinations, analysis options
3. [Materials](03-materials.md)
4. [Objects](04-objects.md) — object types (sections) and reinforcement
5. [Floor Plan](05-floor-plan.md) — grids and grid systems, storeys, members, selection, fill,
   typical floors, loads, CAD drafting
6. [BIM](06-bim.md) — the building model in 3D, end releases and point springs
7. [MEP](07-mep.md) — equipment, sleeves, plumbing, HVAC, electrical
8. [FEM](08-fem.md) — analysis, results, design checks, the design proposal
9. [Substructure](09-substructure.md) — footings, pile caps, rafts, tie beams
10. [BOQ](10-boq.md) — the bill of quantities
11. [Exports](11-exports.md) — report, drawings, IFC, DXF, CSV and exchange files

**More**

- [Importing ETABS, STAAD.Pro and SAP2000 models](12-importing.md)
- [Reference: commands, command line, files](13-reference.md)
- [Packages: design codes and templates](14-packages.md) — the Packages page, templates, code
  that runs only when trusted, offline bundles
- [Glossary](glossary.md)

**Tutorials**

1. [The sample project: Run All, the design proposal, drawings](tutorials/01-sample-project.md)
2. [A new 6-storey RC building](tutorials/02-six-storey-building.md)
3. [Soil report, site map and foundation design](tutorials/03-soil-and-footings.md)
4. [Importing an ETABS model and comparing results](tutorials/04-etabs-import.md)

## Conventions

- **Bold** words are buttons, ribbon tabs, menu entries, commands and field names as they appear
  on screen. *Italic* text is a message SAEngine shows.
- **Ribbon › Group › Button** gives the way to a command: for example **Structure › Edit › Grid
  Systems...** is the *Grid Systems...* button in the *Edit* group of the *Structure* tab.
- Units in this manual are SI: mm for sections and plan positions, m for levels and site
  positions, kN, kN/m², kN·m, MPa. A project can use US customary units instead (see
  [Project Settings](02-project-settings.md)).
- Screenshots were taken from a development build after Alpha 3, in a 1366 × 768 window, with the
  sample project and the tutorial projects. Your window may differ slightly. Features marked
  *(after Alpha 3)* are in the development builds and the next release, not in the 0.0.52 setup.
- All projects, boreholes and models in this manual are synthetic. None of them is a real
  project or a real soil investigation.
