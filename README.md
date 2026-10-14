# SAEngine

SAEngine is an open-source engineering IDE for civil and structural engineers,
built as a native fork of Code - OSS. Engineering features are implemented as
native workbench contributions (not webview extensions), and existing
open-source engines are reused wherever they exist.

## Modules

1. Soil report importer and form generator
2. Project type, design codes (BNBC, ACI, AISC, ...) and design checks
3. Material editor (material composition)
4. Object editor (beam, column, slab, wall, ...)
5. Floor plan CAD
6. 3D BIM model
7. MEP
8. **FEM analysis (SAP2000/ETABS alternative) — in progress**
9. Substructure analysis
10. BOQ analyzer
11. Exporter

## Projects

SAEngine starts with a modal start window (New Project, Open Project, recent projects;
also *File > New Project...* / *Open Project...*). A project is a folder with a
`<name>.saengine` manifest and one folder per module:

```
Office Building/
├─ Office Building.saengine
├─ 01 Soil Report/soil-report.json
├─ 02 Project Settings/project-settings.json
├─ 03 Materials/materials.json
├─ 04 Objects/objects.json
├─ 05 Floor Plan/floor-plan.json
├─ 06 BIM/bim.json
├─ 07 MEP/mep.json
├─ 08 FEM/model.osmodel
├─ 09 Substructure/substructure.json
├─ 10 BOQ/boq.json
└─ 11 Exports/
```

The manifest, the module folders and each module's main file are core items: the
Explorer shows them with a lock and refuses to delete, rename or move them, and they are
recreated if removed outside SAEngine. Users can add and remove anything else. The
`.json` main files are versioned placeholders until their module is implemented.

## Repository layout

| Path | Contents |
|---|---|
| `workbench/` | Code - OSS fork, branded via `workbench/product.json` |
| `workbench/src/vs/workbench/contrib/saengineFem/` | Native FEM model editor (`*.osmodel`) |
| `workbench/src/vs/workbench/services/saengineProject/` | Project detection, core-item protection and restore |
| `workbench/src/vs/workbench/contrib/saengineProject/` | Start window, New/Open Project commands |
| `workbench/src/vs/workbench/contrib/saengineFem/electron-browser/` | Run Analysis / Check Python Runtime commands (desktop) |
| `workbench/src/vs/platform/saengine/` | Shared-process service hosting the Python backend |
| `packages/fem-viewer/` | FEM viewport library: three.js + [That Open Engine](https://github.com/ThatOpen/engine_components), bundled to one ESM file |
| `python/` | `saengine` Python package: JSON-RPC server (pygls) over the opensees-studio core |
| `third_party/opensees-studio/` | Git submodule, pinned: model schema, OpenSeesPy runner, result services |
| `legacy/` | Earlier prototypes kept for reference only (see `legacy/README.md`) |
| `scripts/run-saengine.ps1` | Windows launcher for the branded dev build |

## FEM architecture (module 8)

- **Model format:** the [opensees-studio](https://github.com/ogunc/opensees-studio)
  `.osmodel` JSON schema. Its headless core (Pydantic model, OpenSeesPy runner,
  results store, response spectrum, SRSS/CQC) will be the Python backend.
- **Solver:** OpenSeesPy.
- **Viewport:** `packages/fem-viewer`, loaded lazily by URL from the workbench
  renderer (`resolveAmdNodeModulePath`). The renderer cannot resolve bare module
  specifiers, so the package bundles its dependencies with esbuild. The build also
  removes one `innerHTML` assignment from That Open (its hidden logo), because the
  workbench enforces Trusted Types.

- **Backend process model:** the workbench's shared process
  (`platform/saengine/node/femSolverService.ts`) starts
  - one `python -m opensees_studio.run` per analysis run, reading its JSON-lines
    progress protocol (a solver crash only ends that run), and
  - one long-lived `python -m saengine.rpc` JSON-RPC server (LSP framing,
    `vscode-jsonrpc` ↔ `pygls`) for validation and result queries.

Opening any `*.osmodel` file shows it in the **FEM Model Viewport** (grid, members,
nodes, supports, click selection). Use *Reopen Editor With...* to edit the JSON.
The ▷ **Run Analysis** button in its title bar validates the model, lets you pick
cases, shows solver progress, writes results to `<model>.results/` next to the model,
and prints the result tables to the **SAEngine Analysis** output channel.

## Build and run (Windows)

1. Python backend. OpenSeesPy 3.8 on Windows is built against Python **3.12**
   exactly (`pymanager install 3.12` with the Python install manager):

   ```powershell
   git submodule update --init
   python3.12 -m venv .venv
   .venv\Scripts\python -m pip install -e third_party\opensees-studio -e "python[dev]"
   cd python; ..\.venv\Scripts\python -m pytest
   ```

   The workbench uses `.venv` next to the sources by default; set
   `saengine.python.path` to use another interpreter. *Structural Engineering:
   Check Python Runtime* verifies it.

2. Build the viewer:

   ```powershell
   cd packages\fem-viewer
   npm install
   npm run build
   ```

3. Install and build Code - OSS following [its instructions](./workbench/README.md).
   The viewer is linked into the workbench as `"@saengine/fem-viewer": "file:../packages/fem-viewer"`.
   For client-only rebuilds: `npm run build-fast -- --client-only` in `workbench/`.
   Native modules must be built for Electron; if logs and output channels stay empty
   ("Could not locate the bindings file" for `spdlog`), run
   `npm rebuild @vscode/spdlog` in `workbench/` (needs Visual Studio Build Tools).

4. Launch:

   ```powershell
   .\scripts\run-saengine.ps1
   ```

   The launcher creates a branded `SAEngine.exe` from the cached Electron runtime,
   keeps its profile under `%APPDATA%\SAEngine`, and opens
   `%USERPROFILE%\Documents\SAEngine Projects`.

## License

SAEngine is licensed under the [GNU Affero General Public License v3.0](./LICENSE),
which is required to reuse opensees-studio (AGPL-3.0). The Code - OSS sources in
`workbench/` remain under their original MIT license (`workbench/LICENSE.txt`).
OpenSees/OpenSeesPy are distributed by the Regents of the University of California
under their own license; commercial use of OpenSees requires a license from UC Berkeley.
