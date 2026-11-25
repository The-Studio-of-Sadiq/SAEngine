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

#### Block Editor (BEDIT, BCLOSE, BSAVE, BSAVEAS)
- `BEDIT`: Opens a block definition for editing by name or by picking a block reference. Temporarily stashes model space entities and displays the block definition's linework at the origin `(0,0,0)`, with banner `"Block Editor: <name> — BCLOSE to save or discard"`. All normal draw, modify, and inquiry commands operate on the content in model space.
- `BSAVE`: Writes current block editor linework into the block table record (base point stays at origin) without closing the session.
- `BSAVEAS`: Saves the current block editor linework to a new block name.
- `BCLOSE`: Prompts `[Save/Discard] <Save>`. Saves edits to the block definition or discards changes, restores original model space entities, and regenerates all references (clearing `AcDbRenderingCache`). Attribute definitions inside are preserved.

#### In-Place Reference Editing (REFEDIT, REFCLOSE)
- `REFEDIT`: Picks a block reference to edit its contents in-place at its insertion transform. Non-working-set entities in model space remain visible but are locked from selection and editing.
- `REFCLOSE`: Prompts `[Save/Discard] <Save>`. Maps working set edits back through the inverse transformation $T^{-1}$ into the block definition, restores model space and the block reference, and regenerates references.

#### External References (XREF, -XREF)
- Options: `[Attach/Overlay/Bind/Detach/Reload/?]`
  - `Attach`: Attaches an external DXF file chosen by path. Uses the host `readFile(path): Promise<string>` editor option. Stores the external reference as a block table record with `pathName` (DXF group 1) and `flags` (DXF group 70 bit 4), showing entities greyed with ACI 9 (`UNDERLAY_ACI`).
  - `Overlay`: Attaches an external reference with the overlay flag bit set (bit 8).
  - `?` (List): Lists all attached external references, their paths, flags, and overlay status.
  - `Detach`: Erases all references from model space and removes the block table record.
  - `Reload`: Re-reads the file from its path via `readFile` and updates the block's entities.
  - `Bind`: Converts an external reference into a normal internal block by clearing xref flags and clearing `pathName`.

#### Attribute Synchronization (ATTSYNC)
- `ATTSYNC`: Synchronizes all block references of a chosen block with its current attribute definitions. Adds new attributes with their default values, removes orphaned attributes, retains existing values for matching tags, and updates positions and styles to match current definitions and reference transforms.

#### Dynamic Blocks (BPARAMETER, -DYNPROP)
- `BPARAMETER`: Adds dynamic parameters and actions to a block definition:
  - `Linear` parameter with a `Stretch` action: stretches vertices along the parameter vector.
  - `Flip` parameter with a `Flip` action: mirrors geometry across the flip reflection line.
  - `Visibility` parameter: named visibility states controlling entity visibility.
  - `Rotation` parameter: rotates geometry around a specified center point.
- Storage: Parameters and actions are serialized in XData (`SA_DYNBLOCK_DEF` on block table records/entities, `SA_DYNBLOCK_INST` on references), fully surviving DXF round-trips.
- `-DYNPROP`: Selects a block reference, prompts for parameter name and new value, and regenerates the reference as an anonymous block (`*U<n>`) with modified geometry like AutoCAD.
- Note on custom grips: The underlying `@mlightcad/data-model` exposes only insertion grip points for block references (`subGetGripPoints = [this._position]`), so `-DYNPROP` provides the parameter editing route.

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

### P18: Path Array, Units, and Dimension Styles

#### ARRAYPATH
- `ARRAYPATH`: Distributes copies of selected objects along a path curve (Line, Arc, Circle, Polyline with bulges, Spline, or Ellipse).
- Prompts & Options:
  - `Method`: `Divide` (distributes items evenly across the total path length) or `Measure` (places items at a specified distance along the path).
  - `Base point`: Reference point of the source selection (defaults to selection centroid).
  - `Tangent direction`: Start reference tangent direction specified by two points.
  - `Items`: Number of items (in Divide mode) or item spacing (in Measure mode).
  - `Rows`: Number of rows and row spacing (offsets perpendicular to path tangent in 2D).
  - `Levels`: Ignored in 2D drafting (informational message shown).
  - `Align items`: `Yes` rotates each copy to match the path curve's local tangent angle; `No` translates copies without changing rotation.
  - `Z direction`: Not applicable in 2D.
  - `eXit`: Completes the array operation.
- Associativity: Because `@mlightcad/data-model` does not implement associative array objects, plain entity copies are created with an explanatory message.

#### UNITS / -UNITS
- `UNITS` / `-UNITS` (alias `UN`): Configures drawing unit display formats and system variables:
  - Linear unit format (`LUNITS`): 1 (Scientific), 2 (Decimal), 3 (Engineering), 4 (Architectural), 5 (Fractional).
  - Linear precision (`LUPREC`): 0 to 8 decimal places / fraction denominator power.
  - Angular unit format (`AUNITS`): 0 (Decimal degrees), 1 (Deg/Min/Sec), 2 (Grads), 3 (Radians), 4 (Surveyor's units).
  - Angular precision (`AUPREC`): 0 to 8.
  - Base angle (`ANGBASE`): Direction of angle 0 in radians/degrees (0 = East, 90 = North, etc.).
  - Angular direction (`ANGDIR`): 0 (Counter-clockwise), 1 (Clockwise).
  - Insertion units (`INSUNITS`): Drawing scale unit (default 4 = Millimeters for SAEngine).
- All units settings are persisted as drawing system variables (`$LUNITS`, `$LUPREC`, `$AUNITS`, `$AUPREC`, `$ANGBASE`, `$ANGDIR`, `$INSUNITS`) that round-trip through DXF files.
- Inquiry commands (`DIST`, `ID`, `LIST`, `AREA`, `MEASUREGEOM`) format coordinates, lengths, and angles using pure formatters `formatLength` and `formatAngle` according to the active drawing units.

#### DIMSTYLE / -DIMSTYLE
- `DIMSTYLE` / `-DIMSTYLE` (alias `D`): Command-line dimension style manager:
  - `?`: Lists all dimension styles defined in the drawing database and indicates the current style.
  - `Save`: Creates a new named `AcDbDimStyleTableRecord` from current dimension variables and sets it current.
  - `Restore`: Sets an existing dimension style as the current style.
  - `STatus`: Displays current values of key dimension variables (`DIMSCALE`, `DIMTXT`, `DIMASZ`, `DIMEXE`, `DIMEXO`, `DIMGAP`, `DIMDEC`, `DIMLUNIT`, `DIMTAD`, `DIMBLK`).
  - `Variables`: Inspects the dimension variables of any specified style.
  - `Apply`: Updates selected dimension entities to the current dimension style.
  - `Set`: Directly modifies a dimension variable on the active style.

### AutoCAD 2D coverage

Audited against `@mlightcad/cad-simple-viewer` 1.7.5 and `@saengine/cad-editor`:

| AutoCAD Command | Status | Provider / Notes |
|---|---|---|
| LINE | Available | library (`line`, alias `L`) |
| XLINE | Available | library (`xline`, alias `XL`) |
| RAY | Available | library (`ray`) |
| PLINE | Available | library (`pline`, alias `PL`) |
| POLYGON | Available | library (`polygon`, alias `POL`) & SAEngine (`POLYGONX`) |
| RECTANG | Available | library (`rectang`, alias `REC`) & SAEngine (`RECTANGX`) |
| ARC | Available | library (`arc`, alias `A`) & SAEngine (`ARCX`) |
| CIRCLE | Available | library (`circle`, alias `C`) & SAEngine (`CIRCLEX`, `TTR`, `TTT`) |
| DONUT | Available | SAEngine (`DONUT`, alias `DO`) |
| SPLINE | Available | library (`spline`, alias `SPL`) |
| ELLIPSE | Available | library (`ellipse`, alias `EL`) |
| POINT | Available | library (`point`, alias `PO`) |
| DIVIDE | Available | SAEngine (`DIVIDE`, alias `DIV`) |
| MEASURE | Available | SAEngine (`MEASURE`, alias `ME`) |
| REVCLOUD | Available | library (`revcloud`) |
| WIPEOUT | Available | SAEngine (`WIPEOUT`, P22) |
| REGION | Available | SAEngine (`REGION`, P22) |
| BOUNDARY | Available | SAEngine (`BOUNDARY`, alias `BO`) |
| HATCH | Available | SAEngine (`HATCH`, `HATCHEDIT`) & library (`-hatch`) |
| GRADIENT | Available | SAEngine (`GRADIENT`, P22) |
| TABLE | Available | SAEngine (`TABLE`, alias `TB`) |
| MTEXT | Available | library (`mtext`, alias `MT`, `T`) |
| TEXT | Available | SAEngine (`TEXT`, aliases `DTEXT`, `DT`) |
| MLEADER | Available | SAEngine (`MLEADER`, alias `MLD`) |
| QLEADER | Available | SAEngine (`QLEADER`, P22) |
| DIMLINEAR | Available | library (`dimlinear`, alias `DLI`) |
| DIMALIGNED | Available | SAEngine (`DIMALIGNED`, alias `DAL`) |
| DIMRADIUS | Available | SAEngine (`DIMRADIUS`, alias `DRA`) |
| DIMDIAMETER | Available | SAEngine (`DIMDIAMETER`, alias `DDI`) |
| DIMANGULAR | Available | SAEngine (`DIMANGULAR`, alias `DAN`) |
| DIMARC | Available | SAEngine (`DIMARC`, alias `DAR`) |
| DIMORDINATE | Available | SAEngine (`DIMORDINATE`, alias `DOR`) |
| DIMCONTINUE | Available | SAEngine (`DIMCONTINUE`, alias `DCO`) |
| DIMBASELINE | Available | SAEngine (`DIMBASELINE`, alias `DBA`) |
| QDIM | Available | SAEngine (`QDIM`) |
| DIMSTYLE / -DIMSTYLE | Available | SAEngine (`DIMSTYLE`, `-DIMSTYLE`, `D`) |
| DIMEDIT / DIMTEDIT / DIMOVERRIDE / DIMSPACE / DIMBREAK / DIMJOGGED / DIMJOGLINE | Available | SAEngine (P23a) |
| DIMREASSOCIATE / DIMDISASSOCIATE | Available | SAEngine (P23a, reports lack of data model AcDbDimAssoc support) |
| DIMCENTER / DIMINSPECT | Missing | DIMCENTER covered by CENTERMARK; inspection dimensions not implemented |
| TOLERANCE | Available | SAEngine (`TOLERANCE`, P22) |
| CENTERMARK | Available | SAEngine (`CENTERMARK`, alias `CM`) |
| CENTERLINE | Available | SAEngine (`CENTERLINE`, P22) |
| MOVE | Available | library (`move`, alias `M`) |
| COPY | Available | library (`copy`, aliases `CO`, `CP`) |
| ROTATE | Available | library (`rotate`, alias `RO`) |
| SCALE | Available | SAEngine (`SCALE`, alias `SC`) |
| STRETCH | Available | SAEngine (`STRETCH`, alias `S`) |
| MIRROR | Available | SAEngine (`MIRROR`, alias `MI`) |
| OFFSET | Available | library (`offset`, alias `O`) |
| TRIM | Available | SAEngine (`TRIM`, alias `TR`) |
| EXTEND | Available | SAEngine (`EXTEND`, alias `EX`) |
| FILLET | Available | SAEngine (`FILLET`, alias `F`) |
| CHAMFER | Available | SAEngine (`CHAMFER`, alias `CHA`) |
| BLEND | Available | SAEngine (`BLEND`, P22) |
| ARRAYRECT | Available | SAEngine (`ARRAYRECT`) |
| ARRAYPOLAR | Available | SAEngine (`ARRAYPOLAR`) |
| ARRAYPATH | Available | SAEngine (`ARRAYPATH`) |
| ARRAY / ARRAYEDIT / ARRAYCLOSE | Available | SAEngine (`ARRAY`, alias `AR`, `ARRAYEDIT`, `ARRAYCLOSE`, P23a) |
| BREAK | Available | SAEngine (`BREAK`) |
| BREAKATPOINT | Available | SAEngine (`BREAKATPOINT`) |
| JOIN | Available | SAEngine (`JOIN`, alias `J`) |
| EXPLODE | Available | SAEngine (`EXPLODE`, alias `X`) |
| LENGTHEN | Available | SAEngine (`LENGTHEN`, alias `LEN`) |
| ALIGN | Available | SAEngine (`ALIGN`, alias `AL`) |
| PEDIT | Available | SAEngine (`PEDIT`, P17) |
| SPLINEDIT | Available | SAEngine (`SPLINEDIT`, P17) |
| OVERKILL | Available | SAEngine (`OVERKILL`, P17) |
| ERASE | Available | library (`erase`, alias `E`) |
| UNDO | Available | library (`undo`, alias `U`) |
| REDO | Available | library (`redo`) |
| BLOCK | Available | SAEngine (`BLOCK`, alias `B`) |
| INSERT | Available | SAEngine (`INSERT`, alias `I`) & library (`-insert`) |
| WBLOCK | Available | SAEngine (`WBLOCK`, alias `W`) |
| BEDIT | Available | SAEngine (`BEDIT`, P20) |
| REFEDIT | Available | SAEngine (`REFEDIT`, P20) |
| XREF | Available | SAEngine (`XREF`, P20) |
| ATTDEF | Available | SAEngine (`ATTDEF`, alias `ATT`) |
| ATTEDIT | Available | SAEngine (`ATTEDIT`, aliases `ATE`, `EATTEDIT`) |
| EATTEDIT | Available | SAEngine (`EATTEDIT`) |
| ATTSYNC | Available | SAEngine (`ATTSYNC`, P20) |
| LAYER / -LAYER | Available | SAEngine (`LAYER`, `-LAYER`, `LA`, `-LA`) & library (`-layer`) |
| LAYCUR | Available | SAEngine & library (`laycur`) |
| LAYISO | Available | SAEngine & library (`layiso`) |
| LAYUNISO | Available | SAEngine & library (`layuniso`) |
| LAYOFF | Available | SAEngine & library (`layoff`) |
| LAYFRZ | Available | SAEngine & library (`layfrz`) |
| LAYON | Available | SAEngine & library (`layon`) |
| LAYTHW | Available | SAEngine & library (`laythw`) |
| LAYMCUR | Available | SAEngine (`LAYMCUR`) |
| LAYMRG | Available | SAEngine (`LAYMRG`) |
| LAYDEL / LAYLCK / LAYULK / LAYERP / LAYERCLOSE | Available | library (`laydel`, `laylck`, `layulk`, `layerp`, `layerclose`) |
| LAYWALK / LAYVPI | Available | SAEngine (`LAYWALK`: command-line layer walkthrough; restores states on exit) |
| MATCHPROP | Available | SAEngine (`MATCHPROP`, alias `MA`) |
| PROPERTIES | Missing | Standalone palette UI missing (editor.properties API and CHPROP/CHANGE available) |
| QSELECT | Available | SAEngine (`QSELECT`) |
| SELECTSIMILAR | Available | SAEngine (`SELECTSIMILAR`) |
| FIND | Available | SAEngine (`FIND`, `-FIND`, P23a) |
| FIELD / UPDATEFIELD | Available | SAEngine (`FIELD`, `UPDATEFIELD`, P23a) |
| DIST | Available | SAEngine (`DIST`, alias `DI`) & library (`measuredistance`) |
| AREA | Available | SAEngine (`AREA`) & library (`measurearea`) |
| ID | Available | SAEngine (`ID`) & library (`measurepoint`) |
| LIST | Available | SAEngine (`LIST`, alias `LI`) |
| MEASUREGEOM | Available | SAEngine (`MEASUREGEOM`, alias `MEA`) |
| UNITS / -UNITS | Available | SAEngine (`UNITS`, `-UNITS`, alias `UN`) |
| DIMSTYLE / -DIMSTYLE | Available | SAEngine (`DIMSTYLE`, `-DIMSTYLE`, alias `D`) |
| STYLE | Available | SAEngine (`STYLE`, alias `ST`) |
| MLSTYLE | Available | SAEngine (`MLSTYLE`, `-MLSTYLE`: list, new, set, rename, delete; round trips through DXF) |
| TABLESTYLE | Available | SAEngine (`TABLESTYLE`, `-TABLESTYLE`: list, new, set, delete; TABLE uses current style) |
| MLEADERSTYLE | Available | SAEngine (`MLEADERSTYLE`, `-MLEADERSTYLE`: list, new, set, delete; MLEADER uses current style) |
| PURGE | Available | SAEngine (`PURGE`, alias `PU`) |
| AUDIT | Available | SAEngine (`AUDIT`: fixes missing layers, invalid linetypes, duplicate handles, missing blocks, orphaned dicts) |
| RECOVER | Available | SAEngine (`RECOVER`: reads DXF defensively, runs audit fix and reports dropped elements) |
| ZOOM | Available | library (`zoom`, alias `Z`) |
| PAN | Available | library (`pan`, alias `P`) |
| REGEN | Available | library (`regen`, alias `RE`) |
| DRAWORDER | Available | SAEngine (`DRAWORDER`, P22) |
| GROUP / UNGROUP | Available | SAEngine (`GROUP`, `G`, `UNGROUP`) |
| GEOMCONSTRAINT | Available | SAEngine (`GEOMCONSTRAINT`, P21) |
| DIMCONSTRAINT | Available | SAEngine (`DIMCONSTRAINT`, P21) |
| PARAMETERS | Available | SAEngine (`PARAMETERS`, P21) |
| DATAEXTRACTION | Available | SAEngine (`DATAEXTRACTION`, `-DATAEXTRACTION`, `editor.dataExtraction`: extracts table/CSV, counts identical blocks) |
| FIELD | Available | SAEngine (`FIELD`, `UPDATEFIELD`, P23a) |

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

### Lasso and Selection Cycling

AutoCAD 2015+ lasso selection and AutoCAD selection cycling behaviors:

#### Selection API (`editor`)
- `pickDraftingPolygon(points, mode)`: Selects drafting entities matching a polygon or fence boundary (`'window'` = fully enclosed, `'crossing'` = touched, `'fence'` = crossed by open path).
- `pickDraftingAll(clientX, clientY, tolPx)`: Returns all drafting hits under the cursor sorted by shortest 2D distance to entity linework, providing `{ id, type, layer, distance }`.
- `getSysVar(name)` / `setSysVar(name, value)`: Reads or writes system variables (`LASSO`, `SELECTIONCYCLING`).

#### System Variables and Commands
- `LASSO` (0 = off, 1 = on, default 1): Toggles freehand lasso selection when dragging on empty space.
  - Dragging left-to-right (net) produces a window lasso (objects fully inside, solid blue outline).
  - Dragging right-to-left produces a crossing lasso (touched objects, dashed green outline).
  - Pressing Space during the drag cycles `Window` → `Crossing` → `Fence` lasso.
  - A click-click without drag maintains standard rectangular window/crossing.
  - Inside interactive command `Select objects:` prompts (`getSelection`), typing `LA` or `LASSO` initiates freehand polygon pick points with closing Enter.
- `SELECTIONCYCLING` (0 = off, 1 = on, 2 = on with list, default 2): Controls selection cycling for overlapping objects.
  - When several objects overlap under the cursor, the first click selects the nearest.
  - `Shift+Space` toggles cycling mode; clicking again at the same spot within 300 ms cycles to the next overlapping object.
  - Floor plan members join the cycle list after drafting entities.
  - With `SELECTIONCYCLING=2`, a selection list pop-up appears next to the cursor to directly pick drafting entities (by type and layer) or structural members (by id).

### Parametric Constraints (Package P21)

SAEngine registers AutoCAD-compatible 2D geometric and dimensional parametric constraint commands from `constraintCommands.ts`, `constraintModel.ts`, and `constraintSolver.ts`.

#### Geometric Constraints
- `GEOMCONSTRAINT` (alias `GC`): Interactive command with keywords:
  - `Coincident`: Constrains two points or a point and line/curve together.
  - `Horizontal`: Constrains a line or two points horizontally (`dy = 0`).
  - `Vertical`: Constrains a line or two points vertically (`dx = 0`).
  - `Parallel`: Constrains two lines to have identical orientations (`cross product = 0`).
  - `Perpendicular`: Constrains two lines at 90° (`dot product = 0`).
  - `Collinear`: Constrains two lines along the same infinite line.
  - `Concentric`: Constrains two circles/arcs to share the same center point.
  - `Tangent`: Constrains a line and circle/arc so that the perpendicular distance from center to line equals the radius.
  - `Equal`: Constrains line lengths or circle/arc radii to be equal.
  - `Fix`: Locks a point or entity at its current position. (Generated entities are read-only and may be constraint references only as Fixed).
  - `Symmetric`: Constrains points or lines symmetrically about a reference line.
- Direct command aliases: `GCHORIZONTAL` (`GCH`), `GCVERTICAL` (`GCV`), `GCPARALLEL` (`GCP`), `GCPERPENDICULAR` (`GCPERP`), `GCCOINCIDENT` (`GCCO`), `GCCOLLINEAR` (`GCCOL`), `GCCONCENTRIC` (`GCCON`), `GCTANGENT` (`GCT`), `GCEQUAL` (`GCE`), `GCFIX` (`GCF`), `GCSYMMETRIC` (`GCSYM`).
- `AUTOCONSTRAIN` (alias `AUTOCON`): Inactive or active selection is inspected to automatically infer coincident, horizontal, vertical, parallel, perpendicular, and tangent constraints within angular and geometric tolerances, re-solving the drawing.

#### Dimensional Constraints
- `DIMCONSTRAINT` (alias `DC`): Keywords `Linear`, `Horizontal`, `Vertical`, `Aligned`, `Angular`, `Radial`, `Diameter`.
- Direct command aliases: `DCLINEAR`, `DCHORIZONTAL`, `DCVERTICAL`, `DCALIGNED`, `DCRADIAL`, `DCDIAMETER`, `DCANGULAR`.
- Named parameters: automatically assigned sequential names (`d1`, `d2`, ...). Supports arithmetic expressions with `+`, `-`, `*`, `/`, unary `-`, numbers, and parameter names (e.g. `d2 = d1/2`).
- Annotations: created as plain dimension entities on a dedicated non-plottable `DIMCONSTRAINT` layer (`isPlottable = false`, ACI color 4 cyan), ensuring they are displayed in the CAD editor but excluded from plotted output.

#### Parameters Management
- `PARAMETERS` / `-PARAMETERS` (alias `PARAM`): Command-line management of user and dimensional parameters.
  - `List`: Displays all parameter names, expressions, and evaluated values.
  - `Edit`: Modifies the mathematical expression of a parameter; re-evaluates all dependent parameters and re-solves drawing geometry.
  - `Rename`: Renames a parameter and updates dependent constraints.
  - `Delete`: Deletes a user parameter (refusing parameters referenced by active constraints).
  - `New`: Adds a new user parameter with expression and evaluated value.

#### Constraint Solver & Persistence
- Iterative Levenberg-Marquardt / Newton-Raphson solver: computes minimum-norm update $\Delta X = J^T (J J^T + \lambda I)^{-1} R$, ensuring fixed geometry and unconstrained degrees of freedom stay in place and move the least.
- Over-constrained detection: automatically detects contradictory or over-constrained geometries and reports `"would over-constrain the geometry"`, refusing the modification in an undoable transaction.
- Post-edit re-solving: changes from `MOVE`, `STRETCH`, grip editing, and `PARAMETERS` edits automatically trigger re-solve in an undoable transaction.
- `DELCONSTRAINT` (alias `DELCON`): Removes constraints attached to selected entities and erases associated constraint dimension entities.
- `CONSTRAINTBAR` (alias `CBAR`): Lists all constraints active on selected entities.
- DXF round-trip: SAEngine stores its constraint model and parameters in a dedicated `AcDbXrecord` under `'SAENGINE_CONSTRAINTS'` inside the drawing's resident `MLIGHT_XRECORD` dictionary, ensuring constraints and parameters survive DXF export (`dxfOut`) and re-import (`database.read`).

### Draw, Annotate & Display Order (P22)

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

### Dimension Editing, Arrays, Find & Replace, and Fields (Package P23a)

#### Dimension Editing
- **`DIMEDIT`**: Prompts `[Home/New/Rotate/Oblique] <Home>:`.
  - `Home`: Restores dimension text to default position and angle 0.
  - `New`: Prompts for new dimension text string (empty string or `<>` for default measurement text).
  - `Rotate`: Prompts for rotation angle and sets `textRotation`.
  - `Oblique`: Sets obliquing angle on linear/aligned dimensions (`AcDbAlignedDimension.oblique`).
- **`DIMTEDIT`**: Prompts `Specify new location for dimension text or [Left/Right/Center/Home/Angle]:`.
  - Point pick: moves text to picked location (`textPosition`).
  - `Left` / `Right` / `Center`: aligns text along dimension line.
  - `Home`: resets text position and rotation to default.
  - `Angle`: sets text rotation angle.
- **`DIMOVERRIDE`**: Sets or clears per-dimension variable overrides.
  - Variable overrides (e.g. `DIMTXT`, `DIMSCALE`, `DIMCLRD`, etc.) are serialized into standard AutoCAD `ACAD` `DSTYLE` XData (`1001 ACAD`, `1000 DSTYLE`, `1002 {`, `1070 varCode`, `1040/1070 value`, `1002 }`), fully surviving DXF round-trips.
  - `Clear`: removes `ACAD` DSTYLE XData.
- **`DIMSPACE`**: Prompts `Select base dimension:`, `Select dimensions to space:`, and `Enter value or [Auto] <Auto>:`.
  - Places parallel linear dimensions at equal spacing along the dimension line normal.
  - Auto spacing sets spacing to $2 \times \text{DIMTXT}$.
- **`DIMBREAK`**: Prompts `[Auto/Manual/Remove] <Auto>:`. Stores break flags in XData (`SAENGINE_DIMBREAK`). Native viewer renders standard unbroken lines; break points are tracked in entity metadata.
- **`DIMJOGGED`**: Creates jogged radius dimension stored as `AcDbRadialDimension` with jog parameters in `SAENGINE_DIMJOGGED` XData.
- **`DIMJOGLINE`**: Adds jog line location to linear dimensions stored in `SAENGINE_DIMJOGLINE` XData.
- **`DIMREASSOCIATE` / `DIMDISASSOCIATE`**: Reports that dimension associativity (`AcDbDimAssoc`) is not supported by the underlying `@mlightcad/data-model`.

#### Arrays (ARRAY, ARRAYEDIT, ARRAYCLOSE)
- **`ARRAY`** (alias `AR`): Prompts `[Rectangular/PAth/POlar] <Rectangular>:`.
  - Generates array items and groups source + copies in a named `AcDbGroup` (e.g. `*A1`, `*A2`, ...) stored in `db.objects.group`.
  - Array definition (parameters, source IDs, copy IDs) is stored in a resident `AcDbXrecord` under `SA_ARRAY_<groupName>`, surviving DXF round-trip.
  - True associative arrays (`AcDbAssocArray`) are not supported by `@mlightcad/data-model`; editing is provided via group + Xrecord synchronization.
- **`ARRAYEDIT`**: Picks any item in an array, resolves its group and Xrecord, offers parameter editing (`Columns`, `Rows`, `Spacing`, `Reset`), and regenerates copies in one undoable step.
- **`ARRAYCLOSE`**: Closes array editing.
- **`EXPLODE`**: Exploding any item in an array removes the array group and Xrecord, leaving the items as plain unassociated drawing entities.

#### Text Find & Replace (FIND, -FIND)
- **`FIND` / `-FIND`**: Searches and replaces text across `AcDbText`, `AcDbMText`, `AcDbAttribute`, `AcDbAttributeDefinition`, `AcDbBlockReference` (block attributes), `AcDbDimension` (text overrides), `AcDbTable` (cells), and `AcDbMLeader` (mtextContent).
- **Options**: `Match case`, `Whole words` (`\b`), `Wildcards` (`*`, `?`).
- **MTEXT formatting**: Tokenized parser matches on plain text runs while leaving all formatting tags (`{\f...}`, `\P`, etc.) intact during replacement.
- Replaces all occurrences in a single undoable transaction and reports match and replacement counts.

#### Fields (FIELD, UPDATEFIELD)
- **`FIELD`**: Inserts an `AcDbMText` entity evaluating field codes:
  - `%<\AcVar Date \f "dd-MMM-yyyy">%\`: evaluated using injected or current date.
  - `%<\AcVar Filename>%\`: drawing filename.
  - `%<\AcVar LastSavedBy>%\`: user / author.
  - `%<\AcObjProp Object(%<\_ObjId n>%).Area \f "%lu2%pr2">%\`: referenced object's area (supports `%lu` and `%pr` precision).
  - `%<\AcObjProp Object(%<\_ObjId n>%).Length / Radius / Perimeter>%\`: calculates geometry length, radius, or perimeter.
  - Raw field expression is stored in `ACAD_FIELD` XData; evaluated string is displayed in `mtext.contents`.
- **`UPDATEFIELD`**: Re-evaluates fields on selected entities or all entities in the database.
- **Automatic updates**: Hooked to `commandEnded` in `index.ts` so edits modifying referenced geometry update dependent fields automatically.
- **Pure evaluation**: Implemented in `src/fieldEval.ts`.

#### Styles, Drawing Maintenance & Data Extraction (P23b)
- **`MLSTYLE` / `-MLSTYLE`**: Command line multiline style management:
  - `?` / `List`: lists all defined multiline styles in `db.objects.mlineStyle`, marking current `CMLSTYLE`.
  - `New`: defines new style with arbitrary elements (offset, colour, linetype), cap options (Square, Round, Inner arcs), and optional background fill.
  - `Set`: updates current style `CMLSTYLE`.
  - `Rename`: renames user styles (protects `STANDARD`).
  - `Delete`: deletes unreferenced user styles (protects `STANDARD` and styles in use by `AcDbMLine`).
  - Round-trips cleanly through DXF `OBJECTS` section.
- **`TABLESTYLE` / `-TABLESTYLE`**: Command line table style management:
  - `?` / `List`: lists defined table styles, marking current `CTABLESTYLE`.
  - `New`: defines text style, cell text height, alignment, cell margins, and grid lineweight.
  - `Set`: updates `CTABLESTYLE`.
  - `Delete`: deletes unreferenced user styles (protects `STANDARD`).
  - Synchronizes to resident `AcDbXrecord` under `SAENGINE_TABLESTYLES` to persist across DXF round-trips.
  - Used by `TABLE` command to configure cell and header text heights.
- **`MLEADERSTYLE` / `-MLEADERSTYLE`**: Multileader style manager:
  - `?` / `List`: lists styles in `db.objects.mleaderStyle`, marking current `CMLEADERSTYLE`.
  - `New`: configures arrowhead size, landing gap, dogleg, text height, text style, and content type (`MText` / `Block` / `None`).
  - `Set`: updates `CMLEADERSTYLE`.
  - `Delete`: deletes unreferenced user styles.
  - Used by `MLEADER` command to configure arrowhead size and text height.
  - DXF object dictionary entry names preserved via bundle patch.
- **`AUDIT`**: Database integrity audit and repair tool:
  - Reports and optionally fixes (`[Yes/No]`):
    - Entities on missing layers: moved to layer `0`.
    - Invalid linetype references: reset to `ByLayer`.
    - Zero-length lines and degenerate polylines (< 2 vertices): reported (not removed).
    - Duplicate handles: reallocated via `db.generateHandle()`.
    - Block references to missing block definitions: creates placeholder block definitions.
    - Orphaned dictionary entries: purged.
  - Outputs summary: `"N errors found, M fixed"`.
- **`RECOVER`**: Defensive drawing recovery:
  - Reads DXF file (via host `readFile` callback or current drawing export), sanitizes syntax, applies `AUDIT` repair, and reports dropped or corrected items.
- **`DATAEXTRACTION` / `-DATAEXTRACTION`**: Property and block extraction:
  - Select entities or all model space entities (filters out generated/preview entities).
  - Extracts properties (`Type`, `Layer`, `Color`, `Linetype`, `Length`, `Area`, `Count`, `Name`, block attributes).
  - Identical blocks collapsed into a single row with their count when `Count` column is present.
  - Outputs interactive table entity placed at a point and/or CSV text.
  - Programmatic API `editor.dataExtraction(options?: CadDataExtractionOptions): string` available on `CadEditor`.
- **`LAYWALK`**: Command line layer walkthrough:
  - Steps through layers sequentially (`Next`, `Previous`, `Select by name`, `Exit`).
  - Temporarily isolates each layer (current layer ON/unfrozen, all others OFF).
  - Restores all layer on/off and frozen states exactly on `Exit` or cancellation without permanent drawing changes.

