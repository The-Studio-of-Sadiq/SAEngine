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
  approximated: pinned steel beams and braces as simple connections (...) (1), e.g. D1-Story1
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
  RHS, CHS; `HE200A` = HEA 200), then FreeCAD's profile table (below), then names that carry
  their dimensions, then W/UB/UC estimates
  from depth and mass and placeholder I-shapes (both reported as approximated, the estimates as
  "estimated from the designation — check"). The estimate never fails: heavy shapes that do not
  fit their nominal depth (W14X730 is 22 in deep) grow in depth and width with the flanges held
  at 1/8 of the depth, and W8–W14 column shapes are taken as wide as they are deep. ETABS writes
  its library shapes by name only (`SHAPE "W14X90"`, with `FILE "AISC14"` on the first shape of
  each library); the report names the library. FreeCAD's profile table (`third_party/freecad-profiles`, LGPL-2.1-or-later:
  American W4–W27 (W14 up to W14x132), HEA/HEB/HEM, IPE, INP, UPE, UB, UC, CHS, RHS and the
  Indian I, channel, angle, tee, RHS and SHS sections; its timber and aluminium rows are kept
  for later use), reported as "from the FreeCAD profile
  table, root radius ignored" (the table has no root radii); names that differ only in case or
  separators match (`W14X90` = `W14x90`), and an Indian name without its variant (`ISHB150`)
  takes the first one (`ISHB150(1)`, reported). Names in neither table are estimated as above.
  User-defined shapes (`SHAPE "Steel I/Wide Flange" D B TF TW`) are read exactly. Units of a
  designation follow its family: SHS, RHS, BOX, CHS and ISA are millimetres (`SHS25X25X2.5` is
  25 mm), HSS and TS inches; TUBE, PIPE and L are read in inches only when the thickness is
  below 1 (reported). Names that cannot be read are skipped with their members (reported).
  General sections become the rectangle of the same area and inertia (approximated).
- **Materials**: concrete (f'c), steel (Fy, Fu), E, ν, unit weight.
- **Supports**: SAEngine fixes the bases of the columns and walls of the lowest story itself.
  A pinned restraint (translations only) there becomes a pinned support of the building model,
  which frees the column base's rotations; restraints elsewhere (a brace's foot, a support above
  the base) become building-model supports too. Column bases the file leaves free stay fixed
  (reported). Point springs are not imported; a file without restraints is an **error** in the
  report ("Error: ..." at the top of the warnings, and `errors`).
- **Points below their story**: an ETABS point's third number (`POINT "8" 150 0 3120`) puts it
  that far below the story it is used at.
- **Walls**: a panel that is a rectangle between two stories is a wall. Panels that are not
  (ETABS mesh pieces, the panels round a door or window) are merged with the panels in line with
  them, story by story, into one wall whose gaps become wall openings (doors where they reach
  the floor); panels that make no such wall are reported one by one.
- **Releases**: steel beams and braces released in bending at both ends (`RELEASE "PINNED"`,
  `"M2I M3I M2J M3J"`) get a simple connection (fin plate or gusset, default bolting: check it
  in 04 Objects), which pins them in the analysis. Releases at one end only, of concrete
  members, and axial, shear and torsion releases are reported (members continuous).
- **Property modifiers**: SAEngine has no modifiers per member. Modifiers that are BNBC 2020
  6.3.10.4.1's cracked factors (columns 0.70, beams 0.35, slabs 0.25, walls 0.70 or 0.35 Ig)
  switch on SAEngine's cracked sections for all cases; other values and membrane, axial, shear,
  torsion, mass and weight modifiers are reported as not applied.
- **Column bars**: older files' bar sizes and counts, and ETABS 2016+ patterns
  (`PATTERN "R-4-3" LONGBARAREA 314.2`: 10 bars of 20 mm; `"C-8"` round a circle).
- **Loads**: uniform gravity area loads on floors and roofs become the project's floor and roof
  loads (D, SD, L, Lr); STAAD floor loads on levels with imported slabs, SAP2000 area loads
  (also "uniform to frame", carried as slab pressure). Loads stay per slab: slabs with the same
  loads share an area load, the group with the most area is the floor (roof) load and the other
  groups are area loads of their own, named on their slabs (`areaLoad` of the floor-plan slab).
  ETABS "Other" patterns named as fluid loads (F, F1, FL, Fluid, Water, Liquid, Tank) are
  SAEngine's F in the combinations; their area loads are applied as superimposed dead load (F
  holds the contents of 07 MEP equipment only), reported.
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
  slabs, are reported with their totals (`loads.notCarriedKN`, and a warning with the totals per
  case), not analysed. Add them in SAEngine or check that its own loads cover them.
- **Offsets, insertion points, local axis rotations**: end length offsets, rigid-zone factors,
  cardinal points other than the centroid (a beam's top centre is SAEngine's own placement) and
  joint offsets are reported; members run joint to joint.
- **Reported, not read**: pier and spandrel labels; the mass source where it differs from
  SAEngine's seismic weight (D + SD + 0.25 L, not lumped at the stories); auto seismic
  definitions (user coefficients, UBC, ASCE: SAEngine's BNBC 2020 loads apply).
- Envelope, SRSS and absolute combinations; modal and time-history definitions; non-cartesian
  grids; ribbed, waffle and deck slabs (become solid slabs); auto-select, nonprismatic and
  double sections; American channel names (C, MC) and timber names, which have no table yet.
- Beam bars are left to SAEngine's design (the files give covers only).

## STAAD.Pro files

The reader follows STAAD's command language as its technical reference describes it:

- **Commands** may be abbreviated as STAAD allows (`MEMB LOAD`, `JOINT COORD`, `UNITS`, `SELF`,
  `REP`, `PR` for `PRISMATIC`, `YRA` for `YRANGE`); `UNIT` lines apply to what follows them.
- **Generation**: joint and member generation lines; `REPEAT` repeats the previous line (or
  its last repetition), `REPEAT ALL` everything back to the last `REPEAT ALL` that new data
  followed (`REPEAT ALL 0` starts a section); element incidences with `TO` and `REPEAT`;
  `DEFINE MESH` / `GENERATE ELEMENT` quadrilateral meshes (joints at existing joints' places
  shared, reported: check the element numbering); cylindrical coordinates; `JTORIG`;
  `DELETE MEMBERS`.
- **Groups** (`START GROUP DEFINITION`) in any list; **physical members** (`DEFINE PMEMBER`)
  with their properties, constants and loads on the members that make them up.
- **Releases**: `MEMBER RELEASE` (partial releases of half or more as full ones, springs as
  rigid, reported) and `MEMBER TRUSS` (and a `STAAD TRUSS` model) as members pinned at both
  ends; offsets, cables, tension- and compression-only, cracked and inactive members reported.
- **Beta angles** turn the members: STAAD's local axes (a vertical member's local z along global
  Z with Y up; its local y along global Y with `SET Z UP`) become the angle SAEngine's columns
  take.
- **Supports**: `FIXED`, `PINNED`, `FIXED BUT`; spring directions (`KFY ...`) are left free and
  generated soil springs (`ELASTIC MAT`, `PLATE MAT`) are not imported, both reported (a model
  with springs only is an error); inclined supports are taken in global axes.
- **Loads**: `SELFWEIGHT`, joint loads, member and physical-member loads (`UNI`, `CON`, `LIN`,
  `TRAP` as their mean over the loaded length; local, global and projected directions), element
  pressures (`TRAP` as its mean), floor loads, `REPEAT LOAD`, and `REFERENCE LOAD` with `DEFINE
  REFERENCE LOADS`. A line the reader does not know keeps the load case open; generated wind,
  seismic and moving loads are reported.
- **Section names**: STAAD's compact names are decoded: angles `L40404` (4.0 x 4.0 x 4/16 in:
  legs in tenths of an inch, thickness in sixteenths), tubes `TUB70506` and `TUB25025010.0`
  (metric when the wall has a decimal point), pipes `PIPS30` / `PIPX` / `PIPD` (nominal size,
  ASME B36.10 walls) and `PIP4066.3`, round and rectangular HSS (`HSSP10X0.5`,
  `HSST12X10X0.5`), metric angles (`A125X125X8`, `UA150X150X10`). No placeholder I-shape is
  made for a name of another family.

## SAP2000 files

The reader uses the database tables of the `.s2k` text export (the tables listed in the
module, `saengine.importers.sap2000`), and in addition:

- **Releases** (`FRAME RELEASE ASSIGNMENTS 1 - GENERAL`) as for ETABS; partial fixity reported.
- **Property modifiers** of members and areas multiplied with their sections' own, then the
  ETABS rules above; a file whose concrete members have none gets the warning that SAEngine
  analyses the lateral cases on cracked sections.
- **Library shapes written by name only** (`FromFile=Yes`, no dimensions) through the section
  tables; section-designer sections as general ones; nonprismatic sections reported.
- **Column bars** (`FRAME SECTION PROPERTIES 02 - CONCRETE COLUMN`) with the bar material
  (`MATERIAL PROPERTIES 03E - REBAR DATA`).
- **Frame loads** in local directions on SAP2000's default frame axes turned by the frame's
  angle; projected loads on the projected length.
- **Reported, not imported**: end offsets and insertion points, joint, area and line springs
  (a model with springs only is an error), constraints (SAEngine makes its own floor
  diaphragms), added masses, links, solids, cables, tendons, tension and compression limits,
  temperature and ground-displacement loads, auto lateral loads.

## How the importers are tested

All three readers are tested on synthetic files written from the programs' published formats
(ETABS's e2k text, STAAD.Pro's command language, SAP2000's database tables); they have not been
checked against exports made with licensed copies of the programs yet. The tests reproduce each pattern in synthetic files; check the first import of each
program's real export against its own model (the report's counts and the base reactions under
D).

## Simple steel connections in the analysis

A steel beam or brace type with a `connection` (fin plate, shear end plate, brace gusset) is
pinned at its ends in the derived analysis model (08 FEM): each end connects to a twin node at
the joint, joined to it by a zero-length link (`<member>/pin`) that is stiff in translation only,
so no moment passes and the member carries its simply supported moments; a member pinned at both
ends keeps its torsion at its first end. An end stays rigid where the joint is a support (the
support reaction must stay at the support node) or where nothing else holds the joint's rotation
(a free end); the design then flags the moment reaching that connection ("end moment at a simple
connection", a flag that does not count towards the utilisation).

## Exporting to ETABS

The other way round: `saengine export --format e2k <project> [<out.e2k>]` writes the building as
an ETABS text model (in ETABS: File → Import → ETABS .e2k Text File) and its export report
`<name>.export-report.json` (`saengine.exportReport/1`: `exported` counts, `approximated`,
`skipped`, `warnings`, and `loads.exportedKN` / `notExportedKN` per case). Without a file it
goes to `11 Exports/ETABS/<project>.e2k`. `--units N-mm` writes N and mm (default kN and m);
`--lateral coefficient` writes the earthquake as an ETABS user coefficient instead of
SAEngine's story forces. The code is `saengine.exporters.etabs` (`export_e2k` for a project,
`write_e2k` for parts in memory).

What is written, from the building model (06 BIM), its object types and materials and 02 Project
Settings:

- **Stories and grids**: the stories (the lowest as the base), typical floors (`similarTo`) as
  similar stories of their master; the floor plan's grid lines as one cartesian system.
- **Materials** used by what is exported: concrete (f'c), steel and rebar (fy, fu; fu 1.25 fy
  when missing, reported), E, ν, α, unit weight.
- **Frame sections**, one per object type: concrete rectangles and circles; columns with their
  bars as an ETABS pattern (`PATTERN "R-4-3"`: the perimeter bars split between the faces in
  proportion to their lengths; `"C-8"` round a circle) checked, not designed; beams with their
  covers to the bar centres and the bar areas. Steel shapes that are a shape of SAEngine's steel
  table or of FreeCAD's profile table, and that an ETABS library holds by that name (W in
  AISC16; IPE, HE A/B/M and UPN in Euro; ISMB, ISMC, ISLB, ISWB, ISJB in Indian; UB and UC in
  ArcelorMittal_British), are written by name (`SHAPE "IPE300" FILE "Euro"`: ETABS takes its
  own library's dimensions, reported); the others by their dimensions (I, tube, pipe, channel,
  angle, tee); solid steel bars and rods as ETABS writes them (its rectangle and circle in the
  steel material).
- **Slab and wall properties**: slabs are membranes when 02 Project Settings hands slab loads to
  the beams (one-way load distribution for one-way slabs), thin shells when slabs are shells;
  walls thin shells. Non-structural walls are not elements: their weight is an SD line load on
  the beams under them (the part on no beam is reported with its total).
- **Objects**: columns (split at each story they pass), beams at their story, braces and other
  inclined members, structural walls story by story, slabs, slab openings (with 07 MEP's
  openings and shafts, as the analysis cuts them) and wall openings. A point off a story level
  is written below the story above it (ETABS's point offset). Column angles: the rotation, less
  90° for I, T, L and channel columns (ETABS lays their depth along local 2). Steel beams and
  braces with a simple connection are released in bending at both ends.
- **Stiffness**: with cracked sections (Analysis model → Section stiffness), SAEngine's factors as
  property modifiers: columns I 0.70, beams I 0.35, shell slabs 0.25 in bending, walls 0.70 (0.35
  cracked) on all their stiffness. ETABS's modifiers act in every case: SAEngine's "lateral cases
  only" is reported.
- **Supports and diaphragms**: the bases of the columns and walls at the lowest story fixed (as
  SAEngine fixes them) and the building-model supports; a rigid diaphragm `D1` on the slabs and
  every point of the stories above the base (none when the diaphragm is flexible). Soil springs
  are written as fixed bases (reported).
- **Loads**: patterns D (self-weight from the materials), SD, L, Lr, WX, WY, EX, EY, each with its
  linear static case, and a modal case. The floor and roof loads per slab (finish and partitions
  SD, live L, on the roof Lr). Wind and earthquake are SAEngine's own BNBC 2020 story forces,
  derived as Run All derives the analysis model (about half a minute on the sample), as point
  loads at each story's centre of mass, tied to the diaphragm (a flexible diaphragm: at the
  nearest points); with `--lateral coefficient` the earthquake is ETABS's user coefficient with
  SAEngine's base shear coefficient and height exponent k (ETABS then weighs the building from
  its mass source).
- **07 MEP equipment** (with the plumbing's overhead tanks, the HVAC plant and the electrical
  equipment, as the analysis loads them): empty weight and plinth SD, contents F (a pattern of
  type Other, in the combinations with their F factor) or as 07 MEP's contentsAs says, impact L;
  point loads at the supports, or at the quarter points of the footprint (reported).
- **Mass source**: the elements, SD, the code's share of L (0.25) and F, not lumped at the stories.
- **Combinations**: 02 Project Settings' combinations as linear additions (D on both D and SD).

Not written (each in the report when the project has it): stairs (not in SAEngine's analysis
either), footings, solid blocks, the temperature case and its combination factors, P-Delta, the response spectrum, accidental
torsion, time histories, pushover and construction sequence definitions.

Reading the export back with the importer gives the same stories, members, sections, area loads
and combinations (the tests check this on the sample, a generated building and a synthetic
model); the brick-wall line loads come back as frame loads "not carried over" (the importer
does not take frame loads), and wall openings drawn as opening panels are not read back.
