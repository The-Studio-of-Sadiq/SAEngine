# Exchange formats, the web viewer and automation (alpha 9 L12)

What SAEngine writes for other programs and reviewers, what each file holds, and what is not
verified yet. The `.e2k` export is described in [import.md](import.md) and the CLI in
[cli.md](cli.md).

## Exports from the analysis model

`.s2k`, `.std`, `.f2k`, SAF, SDNF and CIS/2 are written from SAEngine's analysis model, derived exactly as
Run All derives it (`saengine.exporters.analytical`). App: the Exports page (**SAEngine:
Exports**; the SDNF row only when the building has structural steel) or Command Palette,
**SAEngine: Export Analysis Model as ...**; command line: `saengine export <project> --format s2k|std|f2k|saf|sdnf|cis2`.
Files go to `11 Exports/<format>/<project>.<ext>` with `<name>.export-report.json` and `.md`
beside them: what was written, approximated and left out, and the loads left out per case.

| Format | File | Holds |
|---|---|---|
| `.s2k` text | `S2K/<project>.s2k` | joints, restraints, materials, frame sections by shape or by properties, area sections, frames (the members, not the mesh segments) and areas, local axes, end releases, diaphragm constraints, joint masses and the mass source (masses only), load patterns, linear static cases and the modal case (SAEngine's number of modes), joint and member loads (partial and point loads where the joined segments carried different loads), combinations (kN, m) |
| `.std` commands | `STD/<project>.std` | joints and members (the members, not the mesh segments) numbered from 1, shell elements, materials, member and element properties, constants (material, beta), releases, supports, master/slave diaphragms, load cases with joint and member loads (`UNI` partial, `CON`), a `LOADTYPE Mass` case of the lumped masses as weights with `MODAL CALCULATION REQUESTED` and `CUT OFF MODE SHAPE`, combinations (kN, m, `SET Z UP`) |
| `.f2k` text | `F2K/<project>.f2k` | SAFE v20+ database tables (kN, m, °C): points, columns and beams (the members, not the mesh segments; braces left out), floor slabs and walls, grid lines, design strips (`STRIP OBJECT CONNECTIVITY`) along X/Y grid lines across each floor slab, concrete rectangular/circular, steel I and general frame sections, slab/wall properties, local axes, end releases, restraints, load patterns, linear static cases, joint and frame loads, combinations; also **imported** (v12 and v20+ `.f2k` / `.$f2`) |
| SAF `.xlsx` | `SAF/<project>.xlsx` | materials, cross-sections, point connections, curve and surface members, supports, end releases, load groups, cases, combinations, point and curve actions; also **imported** (Import from ETABS, STAAD, SAP2000 or SAF) |
| SDNF | `SDNF/<project>.sdnf` | packets 00 (title), 10 (steel members as pieces, section by table name, grade, rotation, web direction, releases) and 20 (steel plates) |
| CIS/2 | `CIS2/<project>.stp` | LPM/6 analysis model basics: units, materials, section profiles and properties, nodes with restraints, curve elements, load cases with nodal and distributed loads, combinations |

The analysis model splits members at every mesh node (500 mm) and wherever another member meets
them. `.s2k`, `.std` and `.f2k` join the segments back into members (a member is still cut at another
member, a plate, a support, a diaphragm master, an end release or a nodal moment): the loads of
the segments become one uniform load, or partial uniform loads and point loads; the lumped masses
of the inner mesh nodes go to the member's ends by the lever rule (reported). SDNF and the web
viewer write the members as physical pieces; SAF and CIS/2 keep the analysis model's segments.

Left out everywhere (reported): solids, rigid end zones (members run joint to joint), the staged
dead load, plate bending modifiers; the lumped masses in `.f2k`, SAF, SDNF and CIS/2 (`.f2k` also
leaves out braces, diaphragms and the modal case). `.f2k`, SAF, SDNF and CIS/2
have no diaphragm object here: the storey forces at a diaphragm's own master node (the centre of
mass, on no member) are reported as loads left out; a master that is a node of the structure
keeps its loads. CIS/2 writes every load that is not exactly zero. SDNF takes steel only
(concrete members are reported) and no loads, diaphragms or masses (reported as left out, its
report counts no load cases). The report counts what each file holds (pinned ends: one per
end).

### Not verified (for the owner)

No other program was run or its manuals read; the formats were written from their public
descriptions. SAEngine's own readers read `.s2k`, `.std`, `.f2k` and SAF back (tests). To check with a
licensed copy or the format owner:

1. `.s2k`: the table and field names, `ProgramName`, the area section `Type=Shell-Thin`, the
   diaphragm constraint tables, `JOINT ADDED MASS ASSIGNMENTS`, `MASS SOURCE`, `CASE - MODAL 1 -
   GENERAL`, `FRAME LOADS - POINT`, and the local axis angle of vertical members (90° to put the
   depth along Y).
2. `.std`: `SET Z UP` with the default member axes (`BETA` written as SAEngine's rotation), `SLAVE
   XY MASTER` for diaphragms, `STRENGTH FY/FU/FCU`, `TUBE`/`PIPE` parameter order, the mass case
   (`LOADTYPE Mass`, joint weights in X and Y) with `MODAL CALCULATION REQUESTED`.
3. `.f2k` (**Not verified in SAFE**): `PROGRAM CONTROL`, `SLAB PROPERTY DEFINITIONS`, `WALL
   PROPERTY DEFINITIONS - SPECIFIED`, `FLOOR OBJECT CONNECTIVITY`, `STRIP OBJECT CONNECTIVITY`,
   `AREA LOAD ASSIGNMENTS - UNIFORM`, and especially `COLUMN OBJECT CONNECTIVITY`, `BEAM OBJECT
   CONNECTIVITY`, `WALL OBJECT CONNECTIVITY`, `FRAME ASSIGNMENTS - LOCAL AXES`, `FRAME
   ASSIGNMENTS - RELEASES`, `FRAME LOAD ASSIGNMENTS - DISTRIBUTED`, `FRAME LOAD ASSIGNMENTS -
   POINT`, and `JOINT LOAD ASSIGNMENTS - FORCE` (public SAFE v20/v23 samples contain no frame
   connectivity tables, so those tables are written by analogy with ETABS database tables).
4. SAF: sheet and column names, units in headers, the combination layout (case and factor
   columns), `RelConnectsStructuralMember` for releases, the rotation convention.
5. SDNF: the packet 00 line, the packet 10 record layout (cardinal point, orientation vector,
   cut-backs, release codes), packet 20.
6. CIS/2: entity attribute lists of `ANALYSIS_MODEL_3D`, `NODE`, `ELEMENT_CURVE_SIMPLE`,
   `SECTION_PROFILE_*`, the loads. Validate with a CIS/2 / LPM/6 checker before relying on it.

### Steel detailing programs

There is no proprietary link: export IFC (Exports page: the building model with the steel
members' profiles) and open it in the detailing program; SDNF and CIS/2 are there for programs
that read those.

## Web viewer for reviewers

**SAEngine: Export Web Viewer for Reviewers** (or `saengine export --format web`) writes
`11 Exports/Web Viewer/`: `index.html` (opens from disk in any browser, the model and results
inlined), `model.json`, `results.json` (design utilisation per element, the design summary, the
storey drifts), `model.gltf` and the IFC. Members are coloured by their utilisation; clicking one
shows its section and governing check.

The richer three.js view is `packages/web-viewer` (source only). Build it with `npm ci && npm run
build` in that folder (it needs its lock file made once with `npm install`), then copy
`dist/web-viewer.js` to `workbench/resources/saengine/web-viewer/viewer.js` in the release build;
the export then puts it beside `index.html` as `viewer.js`. Without it the page's built-in
wireframe view is used.

## Visual programs

**SAEngine: New Visual Program** makes `12 Automation/graphs/<name>.sagraph.json` and opens the
node editor. Nodes: numbers, texts, lists, ranges and arithmetic; a new building, a parametric
shape and inserting it into the structural model; reading a part, setting a value, scaling the
grid spacings; Run All's steps; the design summary, the largest storey drift, cost and
quantities; exports. **Run** executes the program in the engine and shows each node's outputs.
Nodes that write the project are marked.

## Design studies

**SAEngine: Open Design Studies**: parameters (grid spacing, storey height, concrete grade,
section size or family, any value) with their values make up to 32 variants, every combination or
one parameter at a time. Each runs the building model, analysis, design and bill of quantities on
a copy of the project in the background; the table and chart compare cost, steel, carbon, the
largest utilisation, failures and the largest drift. **Apply** copies the variant's part files
into the project and saves a version.

## Drawing automation

**SAEngine: Auto-Dimension / Auto-Tag Drawing Sheets / Arrange Drawing Labels / Undo Drawing
Automation** work on the generated sheets of `11 Exports/Drawings`; the AI assistant uses them as
its `annotate_drawings` tool while AI edits are allowed. Regenerating the drawings draws the
sheets again without these changes.

## IFC export options, mappings and model diff

`saengine.library.ifc.export_ifc` defaults to `schema="IFC4"` and supports `schema="IFC2X3"` (also
configurable via Project Settings `ifc`, the `export.ifc` action, and `saengine export --format ifc --schema`).

### IFC4 to IFC2X3 entity and PredefinedType mappings

| IFC4 entity / feature | IFC2X3 equivalent | Notes |
| --- | --- | --- |
| `IfcTank`, `IfcPump`, `IfcFan` | `IfcFlowStorageDevice`, `IfcFlowMovingDevice` | `IfcTankType`, `IfcPumpType`, `IfcFanType` preserved |
| `IfcChiller`, `IfcCoolingTower`, `IfcUnitaryEquipment`, `IfcTransformer`, `IfcElectricGenerator`, `IfcElectricFlowStorageDevice` | `IfcEnergyConversionDevice` | IFC2X3 type objects kept (`IfcChillerType`, etc.) |
| `IfcSolarDevice` | `IfcBuildingElementProxy` | No native IFC2X3 solar device |
| `IfcElectricDistributionBoard` | `IfcElectricDistributionPoint` | Equivalent panel entity |
| `IfcPipeSegment`, `IfcDuctSegment`, `IfcCableSegment`, `IfcCableCarrierSegment` | `IfcFlowSegment` | Segments and types mapped consistently |
| `IfcAirTerminal`, `IfcLightFixture`, `IfcFireSuppressionTerminal`, `IfcSanitaryTerminal` | `IfcFlowTerminal` | Type objects preserved |
| `IfcAlarm`, `IfcSensor` | `IfcDistributionControlElement` | Control element types preserved |
| `IfcDistributionSystem` / `IfcDistributionPort` | `IfcSystem` / `IfcDistributionPort` | `PredefinedType` and `SystemType` omitted on IFC2X3 `IfcDistributionPort` |
| `IfcFurniture` / `IfcFurnitureType` | `IfcFurnishingElement` / `IfcFurnishingElementType` | Architectural furnishings |
| `IfcDoorType` / `IfcWindowType` | `IfcDoorStyle` / `IfcWindowStyle` | Opening style entities |
| `IfcMechanicalFastener` | `IfcFastener` | Steel connection bolts in IFC2X3 |
| `IfcFooting.CAISSON_FOUNDATION`, `IfcPile.(BORED\|DRIVEN\|JETGROUTING)`, `IfcCovering.(MOLDING\|SKIRTINGBOARD)`, `IfcBuildingElementProxyType.(COMPLEX\|ELEMENT\|PARTIAL\|PROVISIONFORVOID\|PROVISIONFORSPACE)` | `USERDEFINED` | Unsupported IFC4 predefined enums |
| `IfcWallType.(MOVABLE\|PARAPET\|PARTITIONING\|SOLIDWALL)` | `STANDARD` | Architectural/structural wall types |
| `IfcMapConversion` + `IfcProjectedCRS` | `ePSet_MapConversion` + `ePSet_ProjectedCRS` on `IfcSite` | IFC2X3 property-set convention (millimetre-to-metre scale `0.001`) |
| `IfcBoundaryNodeCondition.TranslationalStiffness*` (boolean) | `IfcBoundaryNodeCondition.LinearStiffness*` (`-1.0` rigid, `0.0` free) | Structural support fixities |

### Structural analysis view, georeferencing and steel connections

- **Structural analysis view** (`includeStructuralAnalysis` / `--analysis`): exports
  `IfcStructuralAnalysisModel` with `IfcStructuralCurveMember` (axes, profiles, materials),
  `IfcStructuralSurfaceMember` (thickness), `IfcStructuralPointConnection` +
  `IfcBoundaryNodeCondition` supports, `IfcStructuralLoadGroup` (`LOAD_CASE` / `LOAD_COMBINATION`),
  point/linear actions, and `IfcRelAssignsToProduct` links to physical members.
- **Georeferencing** (`includeGeoreferencing`, `crs="BTM"\|"UTM"\|"EPSG:<code>"` / `--crs`): writes
  `IfcMapConversion` + `IfcProjectedCRS` (or `ePSet_*` in IFC2X3) from `saengine.gis.crs.ifc_map_conversion`
  when `settings.site` is located, including eastings, northings, orthogonal height, and grid-north rotation.
- **Steel connections** (`includeSteelConnections`): exports connection assemblies from
  `saengine.fabrication.model` grouped as `IfcElementAssembly` with plates (`IfcPlate`), bolts
  (`IfcMechanicalFastener` in IFC4, `IfcFastener` in IFC2X3), bolt holes (`IfcOpeningElement` voids),
  and part/assembly marks in `SAEngine_Fabrication`.

### IFC model diff (`saengine.library.ifc_diff`)

`diff_ifc(before, after, *, file=None)` accepts two IFC file paths, STEP texts, or `ifcopenshell.file`
instances and matches `IfcElement` and `IfcBuildingStorey` entities by `GlobalId` (ignoring transient STEP
`#id` numbers and `OwnerHistory`):

- `added` / `deleted` (alias `removed`) / `changed` lists and `counts`
- Per-change diffs across `type`, `placement` (4x4 local-to-world matrix in mm), `shapeHash`,
  `material`, `name`, `tag`, `storey`, and `properties` (`psets`)
- `colourSummary` (`green` added, `red` deleted, `amber` changed) and `terminalSummary`
- Integrated into `saengine.project.diff.diff_file` for `.ifc` files across project revisions.

## Office server

See [office-server.md](office-server.md).
