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
