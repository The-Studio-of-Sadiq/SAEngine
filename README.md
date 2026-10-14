# SAEngine

SAEngine is an open-source engineering IDE for civil and structural engineers,
built as a native fork of Code - OSS. Engineering features are implemented as
native workbench contributions (not webview extensions), and existing
open-source engines are reused wherever they exist.

## Modules

1. Soil report importer and form generator
2. Project type, design codes (BNBC, ACI, AISC, ...) and design checks
3. Floor plan CAD
4. 3D BIM model
5. MEP
6. **FEM analysis (SAP2000/ETABS alternative) — in progress**
7. Substructure analysis
8. BOQ analyzer
9. Exporter

## Repository layout

| Path | Contents |
|---|---|
| `workbench/` | Code - OSS fork, branded via `workbench/product.json` |
| `workbench/src/vs/workbench/contrib/saengineFem/` | Native FEM model editor (`*.osmodel`) |
| `workbench/src/vs/workbench/contrib/structuralEngineering/` | Activity-bar entry point (placeholder actions) |
| `packages/fem-viewer/` | FEM viewport library: three.js + [That Open Engine](https://github.com/ThatOpen/engine_components), bundled to one ESM file |
| `legacy/` | Earlier prototypes kept for reference only (see `legacy/README.md`) |
| `scripts/run-saengine.ps1` | Windows launcher for the branded dev build |

## FEM architecture (module 6)

- **Model format:** the [opensees-studio](https://github.com/ogunc/opensees-studio)
  `.osmodel` JSON schema. Its headless core (Pydantic model, OpenSeesPy runner,
  results store, response spectrum, SRSS/CQC) will be the Python backend.
- **Solver:** OpenSeesPy.
- **Viewport:** `packages/fem-viewer`, loaded lazily by URL from the workbench
  renderer (`resolveAmdNodeModulePath`). The renderer cannot resolve bare module
  specifiers, so the package bundles its dependencies with esbuild. The build also
  removes one `innerHTML` assignment from That Open (its hidden logo), because the
  workbench enforces Trusted Types.

Opening any `*.osmodel` file shows it in the **FEM Model Viewport** (grid, members,
nodes, supports, click selection). Use *Reopen Editor With...* to edit the JSON.

## Build and run (Windows)

1. Build the viewer:

   ```powershell
   cd packages\fem-viewer
   npm install
   npm run build
   ```

2. Install and build Code - OSS following [its instructions](./workbench/README.md).
   The viewer is linked into the workbench as `"@saengine/fem-viewer": "file:../packages/fem-viewer"`.
   For client-only rebuilds: `npm run build-fast -- --client-only` in `workbench/`.

3. Launch:

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
