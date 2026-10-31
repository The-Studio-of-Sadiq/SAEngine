# SAEngine User Manual

SAEngine version 0.0.42 (Pre Alpha 5). This manual describes what the program does in this
version, part by part, with four step-by-step tutorials. It is written for structural engineers
who know BNBC 2020 and programs such as ETABS and AutoCAD; the [glossary](glossary.md) maps
SAEngine's terms to theirs.

The same content is compiled into one PDF, **SAEngine User Manual**
([SAEngine-User-Manual.pdf](SAEngine-User-Manual.pdf)), by [build.py](build.py).

> **Pre-alpha.** SAEngine is under active development. Check its results independently before
> using them for construction. Every chapter ends with a list of what is limited or could not be
> confirmed in this version.

## Contents

**Getting started**

- [Getting started](00-getting-started.md) — start page, projects, the Project sidebar, Run All,
  versions, archives, settings

**The eleven parts**

1. [Soil Report](01-soil-report.md) — boreholes, SPT, lab tests, site class, bearing, site map
2. [Project Settings](02-project-settings.md) — codes, site, loads, combinations, analysis options
3. [Materials](03-materials.md)
4. [Objects](04-objects.md) — object types (sections) and reinforcement
5. [Floor Plan](05-floor-plan.md) — grids, storeys, members, selection, fill, typical floors,
   New Building from Grid
6. [BIM](06-bim.md) — the building model in 3D
7. [MEP](07-mep.md) — equipment, sleeves, plumbing, HVAC, electrical
8. [FEM](08-fem.md) — analysis, results, design checks, the design proposal
9. [Substructure](09-substructure.md) — footings, pile caps, rafts, tie beams
10. [BOQ](10-boq.md) — the bill of quantities
11. [Exports](11-exports.md) — report, drawings, IFC, DXF, CSV

**More**

- [Importing ETABS, STAAD.Pro and SAP2000 models](12-importing.md)
- [Reference: commands, command line, files](13-reference.md)
- [Packages: design codes and templates](14-packages.md) — the Packages page, templates, code
  that runs only when trusted, offline bundles
- [Glossary](glossary.md)

**Tutorials**

1. [The sample project: Run All, the design proposal, drawings](tutorials/01-sample-project.md)
2. [A new 6-storey RC building](tutorials/02-six-storey-building.md)
3. [Soil report, site map and footing design](tutorials/03-soil-and-footings.md)
4. [Importing an ETABS model and comparing results](tutorials/04-etabs-import.md)

## Conventions

- **Bold** words are buttons, menu entries, commands and field names as they appear on screen.
  *Italic* text in quotes is a message SAEngine shows.
- Units are SAEngine's fixed SI units: mm for sections and plan positions, m for levels and site
  positions, kN, kN/m², kN·m, MPa.
- Screenshots were taken from the development build of 0.0.42 with the sample project and
  synthetic data. Your window may differ slightly.
- All projects, boreholes and models in this manual are synthetic. None of them is a real
  project or a real soil investigation.
