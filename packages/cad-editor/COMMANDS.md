# mlightcad command extension notes

Audited against the installed `@mlightcad/cad-simple-viewer` 1.7.5 bundle and declarations.

- `AcEdCommand` is the native command base (`lib/editor/command/AcEdCommand.d.ts:57`); override `execute(AcApContext)` (`:218` vicinity). Its `trigger()` opens an undo mark and database transaction before execution, aborts on errors, then commits in `finally` (`dist/cad-simple-viewer.js:9891-9935`). Its initial `mode` defaults to Read; set Write for edit commands.
- `AcApDocManager.commandManager` is public (`lib/app/AcApDocManager.d.ts`, `commandManager` getter); `AcEdCommandStack.addCommand(group, globalName, localName, command, aliases?)` is public (`lib/editor/command/AcEdCommandStack.d.ts:99`). Bundle built-ins register commands around `dist/cad-simple-viewer.js:53374-53403`; plugin sample uses the same route (`lib/plugin/AcApPluginExample.js:126`).
- Prompt entry points are on `context.view.editor`: `getSelection`, `getPoint`, `getDistance`, `getAngle`, `getKeywords`, and `getEntity` (`dist/cad-simple-viewer.js:30432-30509`). Prompt options (`AcEdPrompt*Options`) carry messages, base points, rubber-band feedback, keyword collections and default behavior. Selection returns IDs in `AcEdPromptSelectionResult.value.ids`.
- Existing COPY uses selection and point prompts (`dist/cad-simple-viewer.js:47721-47757, 47843-47879`), clones entities and calls `transformBy`; `AcEdPreviewJig` is installed on point options to preview. MOVE/ROTATE use similar selection/point flows. `AcEdCommand.trigger()` owns undo, so mutations inside execute need no second transaction. The helper `AcEdSelectionTransformPreviewJig` is exported for transform previews.
- Database access is through `context.doc.database`; model space is `database.tables.blockTable.modelSpace`. Append with `appendEntity`, retrieve by ID with `getIdAt`, mutate with `database.openEntityForWrite(id)`, and erase with `entity.erase()` (`data-model/lib/database/AcDbBlockTableRecord.d.ts:294, database/AcDbDatabase.d.ts`).
- Limitation: `AcEdCommand.trigger()` commits in its `finally` even after an execute error (though it aborts first); see bundle `9891-9935`. Prompt cancellation should be caught by custom commands before returning. The database API doesn't expose a general replace-in-place method; replace is erase plus append.

SAEngine's `commands.ts` adapts these native APIs, with a nested `transaction(fn)` that executes inside the command's existing undo transaction.

### Block commands

SAEngine registers BLOCK/B, INSERT/I, ATTDEF/ATT, ATTEDIT/ATE/EATTEDIT,
WBLOCK/W, GROUP/G, UNGROUP, and PURGE/PU from `blockCommands.ts`.
WBLOCK emits a standalone DXF string through `CadEditor.onWblock((name, dxfText) => …)`;
the host can use that callback to present its save dialog.

### Layers and Object Properties

SAEngine registers AutoCAD layer management and object property commands from `layerCommands.ts`, `properties.ts`, and `linetypes.ts`.

#### Layers API (`editor.layers`)
- `list()`: Returns all layers with `{ name, color, linetype, lineweight, on, frozen, locked, plot, current, inUse, generated }`.
- `add(name, props)`: Creates a new layer record in the database layer table.
- `set(name, patch)`: Modifies layer properties, including renaming (refusing 0, DEFPOINTS, current layer, and generated layers).
- `delete(name)`: Removes a layer (refusing 0, DEFPOINTS, current layer, in-use layers, and generated layers).
- `current()` / `setCurrent(name)`: Reads or changes `CLAYER`.
- `onDidChangeLayers(listener)`: Subscribes to layer table additions, modifications, and deletions.
- Host helpers exported for new drawings: `ensureLayer(db, name, props)` and `setCurrentLayer(db, name)`.

#### Layer Commands
- `LAYER` / `-LAYER` (aliases `LA`, `-LA`): Command-line options `?` (list), `Make`, `Set`, `New`, `ON`, `OFF`, `Color`, `Ltype`, `LWeight`, `Freeze`, `Thaw`, `LOck`, `Unlock`, `Plot`, `Rename`, `Delete`.
- `LAYCUR`: Changes selected entities to the current layer (`CLAYER`).
- `LAYISO` / `LAYUNISO`: Isolates layers of selected objects by turning off other layers, and restores the saved layer visibility snapshot.
- `LAYOFF`: Turns off the layer of a picked object (prompts confirmation if current layer).
- `LAYFRZ`: Freezes the layer of a picked object (refusing current layer).
- `LAYON`: Turns on all layers in the drawing.
- `LAYTHW`: Thaws all layers in the drawing.
- `LAYMCUR`: Makes the picked entity's layer current.
- `LAYMRG`: Merges source layer into target layer, reassigning all entities and removing the source layer.
- `MATCHPROP` (alias `MA`): Copies properties (color, layer, linetype, lineweight, linetypeScale, text style, dim style, hatch) from source entity to destinations.

#### Properties API (`editor.properties`)
- `get(ids?)`: Returns common values for selection (or active `CLAYER`, `CECOLOR`, `CELTYPE`, `CELWEIGHT`, `CELTSCALE` when empty), reporting `'varies'` for differences. Also computes read-only geometry (length, area, radius, center) using `inquiryGeometry.ts`.
- `set(ids, patch)`: Mutates properties inside an undoable transaction, refusing generated entities and locked layers.

#### Property Commands
- `CHPROP` / `CHANGE`: Changes property (`Color`, `LAyer`, `LType`, `ltScale`, `LWeight`) on selected entities.
- `COLOR` (alias `COL`): Sets current entity color (`CECOLOR`).
- `LWEIGHT` (alias `LW`): Sets current entity lineweight (`CELWEIGHT`).
- `LINETYPE` (aliases `LT`, `-LINETYPE`): Lists (`?`), loads built-in metric patterns (`Load`), or sets current entity linetype (`Set`).
- `LTSCALE`: Sets global linetype scale factor.
- `CELTSCALE`: Sets current entity linetype scale factor.

#### Built-in Metric Linetypes (`acadiso.lin`)
Built-in pattern definitions: `CONTINUOUS`, `DASHED` (dash 12.7 mm, gap -6.35 mm, total 19.05 mm), `DASHED2` (dash 6.35 mm, gap -3.175 mm, total 9.525 mm), `HIDDEN` (dash 6.35 mm, gap -3.175 mm, total 9.525 mm), `HIDDEN2` (dash 3.175 mm, gap -1.5875 mm, total 4.7625 mm), `CENTER` (31.75, -6.35, 6.35, -6.35 mm, total 50.8 mm), `CENTER2` (15.875, -3.175, 3.175, -3.175 mm, total 25.4 mm), `PHANTOM` (31.75, -6.35, 6.35, -6.35, 6.35, -6.35 mm, total 63.5 mm), `DOT` (0, -6.35 mm, total 6.35 mm), `DASHDOT` (12.7, -6.35, 0, -6.35 mm, total 25.4 mm), `BORDER` (12.7, -6.35, 12.7, -6.35, 0, -6.35 mm, total 44.45 mm), and `DIVIDE` (12.7, -6.35, 0, -6.35, 0, -6.35 mm, total 31.75 mm).

### Polyline, Spline & Cleaning Commands

SAEngine registers PEDIT, SPLINEDIT, and OVERKILL from `polyEditCommands.ts` and `polyEditGeometry.ts`.

#### `PEDIT` (alias `PE`)
Edits 2D polylines or converts lines and arcs into polylines:
- **Selection**: Picks a single polyline (or converts a picked line or arc after prompt `Do you want to turn it into one? <Y>`), or supports the `Multiple` (`M`) keyword to select and batch-convert multiple entities.
- **Options**:
  - `Close` / `Open`: Toggles the polyline closed/open state.
  - `Join`: Prompts for objects to join and fuzz distance, joining lines, arcs, and open polylines within fuzz.
  - `Width`: Sets uniform segment start and end widths across the entire polyline.
  - `Edit vertex`: Submenu (`Next`, `Previous`, `Break`, `Insert`, `Move`, `Straighten`, `Tangent`, `Width`, `eXit`), marking the current vertex.
  - `Fit`: Fits smooth circular arcs through vertices as bulges.
  - `Spline`: Quadratic B-spline approximation stored as polyline vertices (SPLINESEGS default 8).
  - `Decurve`: Removes arc bulges or restores original vertices saved prior to fit/spline.
  - `Ltype gen`: Reports data-model limitation (PLINEGEN flag not exposed).
  - `Reverse`: Reverses polyline vertex order, negating bulges.
  - `Undo`: Reverts the last option step within the command session.
  - `eXit`: Completes polyline editing.

#### `SPLINEDIT`
Edits B-splines (`AcDbSpline`):
- `Close` / `Open`: Toggles closed state.
- `Fit data`: Allows `Add`, `Delete`, `Move`, and `Tolerance` editing if the spline retains fit points.
- `Edit vertex`: Adds, deletes, moves, or adjusts weights of spline control points.
- `convert to Polyline` (alias `P`): Samples the spline into an `AcDbPolyline` using precision 0–99.
- `Reverse`: Reverses control points and weights.
- `Undo`: Reverts the last spline edit step.
- `eXit`: Completes spline editing.

#### `OVERKILL`
Removes duplicate and overlapping objects:
- **Settings**: Tolerance (default 0.000001), Ignore (layer, color, linetype, lineweight), Optimize segments within polylines (default ON), Combine co-linear objects that partially overlap (default ON), Combine co-linear objects end to end (default OFF).
- Removes zero-length lines and zero-radius circles.
- Removes duplicate consecutive polyline vertices.
- Removes exact duplicates across geometry types within tolerance.
- Merges overlapping collinear lines into single lines.
- Reports `"N duplicate(s) deleted, M overlapping object(s) or segment(s) deleted"` in one undoable transaction.

### AutoCAD 2D Coverage (Draw, Annotate & Display Order)

| Command | Aliases | AutoCAD Behavior | SAEngine Implementation | Status / Limitations |
| :--- | :--- | :--- | :--- | :--- |
| `WIPEOUT` | — | Masking boundary with frames [ON/OFF/Display not plot] or from polyline | `wipeoutCommand`: uses `AcDbWipeout` with normalized clip boundary, dimensions, and position; respects WIPEOUTFRAME (0, 1, 2) | Fully supported; works with DRAWORDER |
| `REGION` | `REG` | Converts 2D closed planar loops into 2D regions | `regionCommand`: reuses `detectLoopsFromObjects` boundary detection to generate closed loops tagged with `AUTOCAD_REGION` XData | Complete (represented as closed polyline loop set tagged with XData) |
| `UNION` | `UNI` | Boolean union of regions or solid bodies | `unionCommand`: performs 2D polygon boolean union via Greiner–Hormann clipping with arc chord-approximation | Complete for 2D regions |
| `SUBTRACT` | `SU` | Boolean difference of regions or solid bodies | `subtractCommand`: performs 2D polygon difference via Greiner–Hormann clipping | Complete for 2D regions |
| `INTERSECT` | `IN` | Boolean intersection of regions or solid bodies | `intersectCommand`: performs 2D polygon intersection via Greiner–Hormann clipping | Complete for 2D regions |
| `MASSPROP` | `MP` | Computes engineering mass properties (area, perimeter, centroid, moments of inertia, radii of gyration, principal axes) | `masspropCommand`: calculates 2D Green's theorem area integrals, moments of inertia about centroid ($I_{xx}, I_{yy}, I_{xy}$), radii of gyration, and principal moments ($I, J$) | Full engineering mass properties report |
| `GRADIENT` | `GD` | Gradient hatch fill (9 patterns, 1- or 2-color, angle, shift/centred) | `gradientCommand`: creates `AcDbHatch` with `GradientObject` type, gradient pattern, colors, angle, and shift; round trips in DXF | Data model and DXF fully supported; viewer does not implement WebGL shader gradient rendering |
| `TOLERANCE` | `TOL` | Geometric Dimensioning & Tolerancing (GD&T) feature control frame | `toleranceCommand`: creates `AcDbFcf` with standard `%%v` delimiter, symbol, tolerance 1/2 with diameter and material modifiers (MMC/LMC/RFS), and datums A/B/C | Full data model, DXF, and frame layout support |
| `CENTERLINE` | `CL` | Associative/geometric centerline between parallel or converging lines | `centerlineCommand`: computes centerline midway between lines or along angle bisector, extended by `CENTEREXE` with `CENTER` linetype | Complete |
| `BLEND` | `BLE` | Creates a tangent (G1) or smooth (G2) spline between endpoints of two open curves | `blendCommand`: computes curve endpoint tangents and generates clamped cubic `AcDbSpline` | Complete |
| `QLEADER` | `LE`, `LEADER` | Quick leader with configurable settings (MText, Tolerance, Block, None, Copy, arrowhead, point limits) | `qleaderCommand`: creates `AcDbLeader` entity linked via `associatedAnnotation` to `AcDbMText` or `AcDbFcf` | Complete |
| `DRAWORDER` | `DR` | Modifies entity draw/display order (Above, Under, Front, Back) | `draworderCommand`: updates `AcDbSortentsTable` in `database.objects.sortentsTable` and reorders `modelSpace._entities` | Complete; survives DXF round trip via `SORTENTSTABLE` |
| `TEXTTOFRONT` | — | Moves text, dimensions, and leaders to the front | `texttofrontCommand`: batches text, dimension, and leader entities to the top of draw order | Complete |
| `HATCHTOBACK` | — | Moves all hatch entities to the back | `hatchtobackCommand`: batches all `AcDbHatch` entities to the bottom of draw order | Complete |

#### Detailed Command Reference

##### `WIPEOUT`
- **Usage**: Prompts `Specify first point or [Frames/Polyline] <Polyline>:`.
- **Options**:
  - `Polyline`: Select a closed polyline. Prompts `Erase polyline? [Yes/No] <No>:`. Creates an `AcDbWipeout` entity masking underlying objects.
  - `Frames`: Sets `WIPEOUTFRAME` mode (`ON` = 1, `OFF` = 0, `Display` = 2).
  - Point sequence: Pick at least 3 points to define a closed polygon.
- **Data Model**: Implemented using `AcDbWipeout` with normalized `clipBoundary` and bounding coordinates. Paints layout background to mask objects behind it in the draw order.

##### `REGION`, `UNION`, `SUBTRACT`, `INTERSECT`, `MASSPROP`
- **`REGION`**: Converts selected closed curves/loops into region entities. Stored as closed `AcDbPolyline` entities tagged with `AUTOCAD_REGION` XData.
- **`UNION`**: Combines overlapping regions into a unified region boundary using Greiner–Hormann polygon clipping.
- **`SUBTRACT`**: Subtracts one set of regions from another, producing composite boundaries and holes.
- **`INTERSECT`**: Finds the overlapping geometric intersection of selected regions.
- **`MASSPROP`**: Outputs complete 2D engineering mass properties:
  - Total area and perimeter
  - Bounding box
  - Centroid coordinates ($C_x, C_y$)
  - Moments of inertia ($I_{xx}, I_{yy}$) and product of inertia ($I_{xy}$) about the centroid
  - Radii of gyration ($k_x, k_y$)
  - Principal moments ($I, J$) and directions about the centroid

##### `GRADIENT`
- **Usage**: Prompts `Pick internal point or [Select objects/Pattern/Color1/Color2/Angle/Centred] <Pick>:`.
- **Patterns**: `LINEAR`, `CYLINDER`, `INVCYLINDER`, `SPHERICAL`, `INVSPHERICAL`, `HEMISPHERICAL`, `INVHEMISPHERICAL`, `CURVED`, `INVCURVED`.
- **Options**: One-color (tint/shade) or two-color, start/end RGB colors, pattern angle, shift/centred offset.
- **Round trip**: Preserved across DXF save/load in `AcDbHatch` group codes 450, 460, 470, 471, etc. Viewer renders solid/boundary outline since WebGL shader gradients are not implemented in `@mlightcad/cad-simple-viewer`.

##### `TOLERANCE`
- **Usage**: Prompts for GD&T characteristic symbol (`POS`, `FLAT`, `CIRC`, `STR`, `CYL`, `PERP`, `PARA`, `ANG`, `RUN`, `TRUN`, `PROF_L`, `PROF_S`, `CONC`, `SYM`), tolerance value with optional diameter (`%%c`) and material condition modifier (`MMC` `%%m`, `LMC` `%%l`, `RFS` `%%s`), optional second tolerance, datums A/B/C, and insertion point.
- **Data Model**: Stored as native `AcDbFcf` (`TOLERANCE` in DXF), formatted with standard `%%v` slot delimiters.

##### `CENTERLINE`
- **Usage**: Prompts `Select first line:` and `Select second line:`.
- **Behavior**: For parallel lines, places centerline equidistant between them spanning the projected segment range, extended at both ends by `CENTEREXE` (default 3.75). For converging lines, places centerline along the angle bisector. Formatted with `CENTER` linetype.

##### `BLEND`
- **Usage**: Prompts `Select first curve or [Continuity] <Continuity>:`.
- **Behavior**: Smoothly blends between two open curve endpoints with matching tangent continuity (G1) using a cubic `AcDbSpline`.

##### `QLEADER`
- **Usage**: Prompts `Specify first leader point or [Settings] <Settings>:`.
- **Settings**: Annotation type (`MText`, `Tolerance`, `Block`, `None`, `Copy`), number of points, arrowhead style.
- **Behavior**: Creates an `AcDbLeader` entity linked via `associatedAnnotation` to `AcDbMText` or `AcDbFcf`.

##### `DRAWORDER`, `TEXTTOFRONT`, `HATCHTOBACK`
- **`DRAWORDER`**: Reorders objects with `Front`, `Back`, `Above object`, or `Under object`.
- **`TEXTTOFRONT`**: Moves `Text`, `Dimensions`, `Leaders`, or `All` annotations in front of other objects.
- **`HATCHTOBACK`**: Sends all `HATCH` entities behind other geometry.
- **Data Model & DXF**: Updates `AcDbSortentsTable` in `database.objects.sortentsTable` (written to DXF `SORTENTSTABLE` / `ACAD_SORTENTS`) and synchronizes model space entity list for immediate in-memory and render order.
