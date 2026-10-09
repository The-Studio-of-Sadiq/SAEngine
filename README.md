# SAEngine

SAEngine is an open-source engineering IDE foundation for structural analysis,
with a path toward general-purpose finite-element analysis and future CAD and
BIM modules. The target workbench is the adjacent Code - OSS checkout; engineering
capabilities are exposed through independently runnable, versioned local services.

## Architecture direction

- **Workbench:** first-party Code - OSS extension in `extensions/saengine`.
- **Engineering API:** Python service in `src/saengine/service`, independent of
  the desktop GUI and bound to loopback by default.
- **First engineering slice:** create a regular 3D frame from project grids and
  stories, assign joint loads, and run linear-static analysis through the service.
- **Existing desktop UI:** the PySide application and embedded editor remain in
  the repository as an early prototype while the Code - OSS workbench evolves.

Services own domain operations and communicate through explicit, versioned
interfaces. The current API provides `GET /api/v1/health`,
`POST /api/v1/models/grid-frame`, and
`POST /api/v1/analysis/linear-static`. CAD and BIM APIs can be added and versioned
without coupling their runtimes to the workbench.

## First frame-analysis scope

The grid-frame generator creates joints at every grid/story intersection,
continuous columns between levels, and beams along each floor grid line. The
generated model initially shares one user-supplied isotropic material and one
prismatic section across all members, fixes all six degrees of freedom at the
lowest level, and creates an empty static load case. The extension has commands
to generate this model, assign six-component joint loads, and run a selected
load case.

The solver is an initial sparse direct-stiffness implementation for linear,
elastic, prismatic 3D Euler-Bernoulli frame members. It supports joint forces
and moments and reports joint displacements, support reactions, and member-end
forces. It does not yet support distributed/member loads, geometric or material
nonlinearity, dynamic analysis, diaphragm constraints, automated design checks,
or validated code-level design results. Treat it as an engineering prototype,
not as a substitute for independently verified professional analysis software.
All solver input uses consistent base units: kN, m, kN/m², m², and m⁴.

## Run the local service

Python 3.11 or newer is required. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m saengine.service
```

The service listens on `http://127.0.0.1:8765` by default. Verify it from another
terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/v1/health
```

The service binds only to loopback by default. Use `--host` to choose a different
interface only when remote access is intentionally required.

## Open the SAEngine workbench

The adjoining Code - OSS source checkout is rebranded through its `product.json`
as the SAEngine desktop product, with its own application name, user-data
directory, URL scheme, and structural-frame icon. The extension supplies the
SAEngine workbench landing screen and engineering commands.

On Windows, launch that branded development build (not the installed VS Code app)
from this repository:

```powershell
.\scripts\run-saengine.ps1
```

The first launch uses the adjoining Code - OSS checkout's compiled output and
cached Electron runtime. Its window is branded **SAEngine** and opens the
SAEngine workbench. The launcher creates a separate
SAEngine executable from the cached runtime, applies the SAEngine icon, and
leaves the original Code - OSS executable untouched.

Start the Python service separately if you want to use analysis commands. In
the workbench, the Command Palette provides **SAEngine: Open Welcome Screen**,
**SAEngine: Generate Grid Frame Model**, **SAEngine: Add Joint Load**, and
**SAEngine: Run Linear-Static Analysis**. **SAEngine: Check Engineering Service**
verifies the connection. Configure `saengine.serviceUrl` to point to another
service URL if needed.

The analysis endpoint accepts a request containing a serialized `FrameModel`
and a `load_case_id`. The grid-frame endpoint accepts serialized project `grids`
and `stories`, plus explicitly supplied material and section properties; it
does not silently choose engineering properties.

The extension uses only the Code - OSS extension API and Node.js built-ins; no
additional extension dependencies are required.

## Test

```powershell
python -m pytest
```

## Legacy desktop prototype

The earlier PySide6 application is still available through `saengine` or
`python -m saengine`. It currently provides project setup, grids, stories, and
an embedded Code - OSS web view; it is not yet the target Code - OSS-first
workbench described above.

## License

MIT License — free for everyone, forever.
