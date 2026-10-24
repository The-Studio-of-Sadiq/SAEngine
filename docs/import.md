# Importing ETABS, STAAD.Pro and SAP2000 models

SAEngine creates a new project from the text export of another analysis program:

| Program | File | How to export it there |
| --- | --- | --- |
| ETABS | `.e2k` (also `.$et`) | File → Export → ETABS .e2k Text File |
| STAAD.Pro | `.std` | the input file itself |
| SAP2000 | `.s2k` (also `.$2k`) | File → Export → SAP2000 .s2k Text File |

In the app: **Import from ETABS, STAAD or SAP2000...** on the start page or in the ≡ menu. From
the command line:

```console
> saengine import "Office.e2k" "D:\Projects" --name "Office"
Imported ETABS model Office.e2k as Office into D:\Projects\Office (units kn-m).
  imported: 3 stories, 5 gridLines, 12 columns, 14 beams, 1 braces, 4 slabs, 1 walls, ...
  approximated: end releases ignored (members are continuous) (1), e.g. D1-Story1
  skipped: point loads (1), e.g. 5-Story2 Live
  loads not carried over: L 20 kN, D 60 kN
```

The project is written into `<dest>/<name>`: 02 Project Settings (the area loads and the load
combinations), 03 Materials, 04 Objects (one type per frame section and shell thickness), 05 Floor
Plan (stories and grid lines, where the model maps onto them), 06 BIM (the elements) and
`import-report.json`; the other parts start empty, as in a new project. An existing, non-empty
folder is refused. Then derive and analyse as usual (Run All).

## Units

Every importer reads the file's own unit line and converts to SAEngine's fixed units (mm, N,
MPa): ETABS `$ CONTROLS UNITS "KN" "M" "C"` (kip-ft, kip-in, kN-m, N-mm, kgf-m, tonf-m, ...);
STAAD `UNIT` lines, which may change the units anywhere in the file; SAP2000 `PROGRAM CONTROL
CurrUnits`. A file without a unit line is read in kN and m, with a warning.

## What is imported

- **Geometry**: joints/points, frames (columns, beams, braces: vertical members are columns,
  horizontal ones beams, the rest braces), shells (floors and walls) with their thickness,
  ETABS stories and cartesian grids, rectangular plan openings.
- **Sections**: rectangular and circular concrete; I, channel, angle, tee, box (SHS/RHS) and pipe
  steel from their dimensions. Sections named only by a designation are read the same way by all
  three importers: SAEngine's standard section table first (IPE, HEA, HEB, ISMB, ISMC, L, SHS,
  RHS, CHS; `HE200A` = HEA 200), then names that carry their dimensions, then W/UB/UC estimates
  from depth and mass and placeholder I-shapes (both reported as approximated). Units of a
  designation follow its family: SHS, RHS, BOX, CHS and ISA are millimetres (`SHS25X25X2.5` is
  25 mm), HSS and TS inches; TUBE, PIPE and L are read in inches only when the thickness is
  below 1 (reported). Names that cannot be read are skipped with their members (reported).
  General sections become the rectangle of the same area and inertia (approximated).
- **Materials**: concrete (f'c), steel (Fy, Fu), E, ν, unit weight.
- **Supports**: restraints at the base.
- **Loads**: uniform gravity area loads on floors and roofs become the project's floor and roof
  loads (D, SD, L, Lr); STAAD floor loads on levels with imported slabs, SAP2000 area loads
  (also "uniform to frame", carried as slab pressure).
- **Combinations**: linear combinations on SAEngine's cases (Dead/Superimposed → D/SD, Live → L,
  Roof Live → Lr, wind → WX/WY, seismic → EX/EY by the axis in the name or, for ETABS response
  spectrum cases, their ACCEL directions). Combinations of combinations are expanded;
  duplicates are dropped. Where the file's roof live load sits in the Live pattern (or the
  reverse), the combination factors follow it (reported).

## What is approximated or skipped

The import report lists each with a count and examples; the app shows it after the import and
again with **SAEngine: Show Import Report** (the last import). In short:

- **Wind and earthquake**: SAEngine applies its own BNBC 2020 loads in place of the file's
  lateral patterns; check the site, occupancy and structural system in 02 Project Settings.
  Response spectrum terms become the equivalent static EX/EY (the spectrum function, damping and
  scaling are not imported).
- **Loads not carried over**: point and frame loads, and STAAD floor loads on levels with no
  slabs, are reported with their totals (`loads.notCarriedKN`), not analysed. Add them in
  SAEngine or check that its own loads cover them.
- **Releases, offsets, insertion points, local axis rotations** are ignored (members are
  continuous); pinned bases are analysed as fixed; springs are skipped. To pin imported steel
  beams or braces, give their object type a simple connection (fin plate, end plate or gusset)
  in 04 Objects: SAEngine then pins those member ends in the analysis (see below).
- Envelope, SRSS and absolute combinations; modal, time-history and mass-source definitions;
  non-cartesian grids; ribbed, waffle and deck slabs (become solid slabs); auto-select,
  nonprismatic and double sections; STAAD compact tube/pipe/channel names.
- Beam and column bars are left to SAEngine's design (the files give covers only).

The parsers were written from the formats' published structure and tested on synthetic files;
check the first import of each program's real export against its own model (the report's
counts and the base reactions under D).

## Simple steel connections in the analysis

A steel beam or brace type with a `connection` (fin plate, shear end plate, brace gusset) is
pinned at its ends in the derived analysis model (08 FEM): each end connects to a twin node at
the joint, joined to it by a zero-length link (`<member>/pin`) that is stiff in translation only,
so no moment passes and the member carries its simply supported moments; a member pinned at both
ends keeps its torsion at its first end. An end stays rigid where the joint is a support (the
support reaction must stay at the support node) or where nothing else holds the joint's rotation
(a free end); the design then flags the moment reaching that connection ("end moment at a simple
connection", a flag that does not count towards the utilisation).
