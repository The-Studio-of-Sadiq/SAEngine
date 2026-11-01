# Installing SAEngine on Windows (beta)

SAEngine ships as a per-user Windows x64 installer, `SAEngine-x64-user-setup-<version>.exe`.
It contains the workbench (a Code - OSS build), the 3D viewers, and a self-contained Python
3.12 with the analysis backend (`saengine`, `opensees-studio`, OpenSeesPy, gmsh,
IfcOpenShell, ...). An engineer needs nothing else: no Python, no repository, no
administrator rights.

## Installing

1. Run `SAEngine-x64-user-setup-<version>.exe`.
2. Windows SmartScreen will say *"Windows protected your PC"* because the beta installer is not
   code-signed (see [Known issues](#known-issues)). Choose **More info**, then **Run anyway**.
   Check first that the file's SHA-256 matches the `.sha256` file published with it:
   `Get-FileHash .\SAEngine-x64-user-setup-<version>.exe`.
3. Accept the licence (GNU AGPL-3.0) and keep the default folder,
   `%LOCALAPPDATA%\Programs\SAEngine`. No administrator rights are needed.

The installer adds a Start-menu entry and, by default, SAEngine to *Open with* for its file
types, including the `.civil` project archive (double-click one to open it in SAEngine). The
task *Add the saengine command to PATH* is unticked by default: tick it to use the SAEngine
command line (`saengine ...`, see `docs/cli.md`) from any terminal. `bin\saengine.cmd` runs
the bundled Python (`python -I -m saengine.cli`); `bin\saengine-app.cmd` opens a folder or
file in the SAEngine window.

Unattended install (for IT): `SAEngine-x64-user-setup-<version>.exe /VERYSILENT /NORESTART
/MERGETASKS="!runcode"`; add `/DIR="<folder>"` for another folder, `/TYPE=compact` for the core
only, or `/COMPONENTS="energyplus,librecad"` for a chosen set (see [Components](#components)).

## Components

The setup asks for a type on its *Select Components* page:

| Type | What it installs |
| --- | --- |
| **Full** (the default, also for an unattended install) | the core and every component below |
| **Compact** | the core only |
| **Custom** | the core and the components you tick |

| Component (`/COMPONENTS=` name) | Contents | Without it |
| --- | --- | --- |
| **SAEngine** (always) | the workbench, the bundled Python with the backend, OpenSeesPy, gmsh, IfcOpenShell, all MEP disciplines, BNBC 2020 | — |
| **Energy simulation** (`energyplus`) | EnergyPlus 26.2.0, a separate program (`resources\energyplus`) | 7 MEP › HVAC shows SAEngine's estimate of the cooling loads instead of the EnergyPlus design-day run |
| **CAD editor** (`librecad`) | LibreCAD 2.2.1.6, a separate GPL-2.0-only program with its GPL and Qt licence texts (`resources\librecad`); shipped alongside, never linked | *Open in LibreCAD* opens the DXF in the program Windows uses for `.dxf` files; the drawings themselves are made by SAEngine either way |
| **DWG import** (`libredwg`) | GNU LibreDWG 0.14's `dwg2dxf`, a separate GPL-3.0-or-later program (`resources\libredwg`) | a DWG underlay or import asks for the drawing as DXF |
| **AI assistant** (`ai`) | the GitHub Copilot chat, a built-in extension (`resources\app\extensions\copilot`, about 280 MB, most of it the Copilot runtime); needs a GitHub account | no chat inside SAEngine; assistants outside it (Claude Code, Claude Desktop) still connect through *Allow AI Assistants to Control This Window* ([AI assistants](../ai-assistants.md)) |
| **Git** (`git`) | the Git, GitHub and merge-conflict extensions (about 13 MB); GitHub sign-in comes with Git or the AI assistant | no Git integration; SAEngine's own project versions work without it |
| **Collaboration** (`collaboration`) | port forwarding and Microsoft sign-in for remote access (about 5 MB); live collaboration will be part of it once it exists | SAEngine works on this computer only |

Sizes on disk, as the build prints them (see [Building the installer](#building-the-installer);
measured on a local build, 2026-10-30):

| Part | On disk |
| --- | --- |
| Energy simulation (EnergyPlus minimal runtime) | 59 MB |
| CAD editor (LibreCAD, trimmed, with its Qt and VC++ DLLs) | 115 MB |
| DWG import and export (LibreDWG) | 30 MB |
| all three components | 204 MB |

The core is the rest: the bundled Python alone is about 780 MB. A local build's core
(3.1 GB) is larger than a release's because it packages the Copilot extension compiled from
sources; the release build's table is in its log. The setup of that local build with all three
components was 711 MB.

**A missing component is a state, not an error.** Where SAEngine uses the program it says it
is not installed and offers **Add Component...**: the HVAC results and *Calculate Loads*
(EnergyPlus), *Open in CAD* (LibreCAD, once, with *Don't Show Again*), a DWG underlay in the
floor plan (LibreDWG), opening the chat (the AI assistant: SAEngine has no extension gallery,
so the chat's own install step is replaced by *Add Component...*), and the Source Control view
(Git). **Help › Installer Components...** lists all six with their state:
*installed*, *not installed*, or *not installed by the setup; using ...* when SAEngine finds
the program elsewhere (`SAENGINE_ENERGYPLUS`, `SAENGINE_LIBREDWG`, the `saengine.cad.program`
setting, or a LibreCAD in `%ProgramFiles%`).

**Adding a component later** runs the setup again; SAEngine does not download programs by
itself. *Add Component...* asks for the setup of the version you have
(`SAEngine-x64-user-setup-<version>.exe` from the release page; *Open Release Page* opens it)
with its `.sha256` file next to it. SAEngine checks the setup's SHA-256 against that file
and only then runs it with `/COMPONENTS=` set to the components already installed plus the new
one, so the wizard opens with them ticked. The setup asks to close SAEngine, adds the
component and keeps projects and settings. A setup of another version asks first, since it also
updates (or downgrades) SAEngine.

By hand: run the setup again and choose *Custom*, or from a terminal
`SAEngine-x64-user-setup-<version>.exe /COMPONENTS="energyplus,librecad,libredwg"`. The list is
the whole selection: a component left out is **removed** (the setup deletes its folder), which
is also how to remove one. An update without `/COMPONENTS=` or `/TYPE=` keeps the components
chosen before; an update from a version without components (up to Pre-Alpha-v7) installs as
Full.

## Uninstalling

*Settings > Apps > Installed apps > SAEngine > Uninstall*, or run
`%LOCALAPPDATA%\Programs\SAEngine\unins000.exe` (`/VERYSILENT` for unattended). This removes
the program folder, including the bundled Python. It keeps your projects (by default in
`Documents\SAEngine Projects`), your settings (`%APPDATA%\SAEngine`) and your extensions
(`%USERPROFILE%\.saengine`); delete those folders by hand for a clean slate.

## Where things live

| What | Where |
| --- | --- |
| Program | `%LOCALAPPDATA%\Programs\SAEngine\SAEngine.exe` |
| Workbench (app root) | `...\SAEngine\resources\app` |
| Bundled Python | `...\SAEngine\resources\python\python.exe` (CPython 3.12.10, x64) |
| Command line | `...\SAEngine\bin\saengine.cmd` (the window launcher: `bin\saengine-app.cmd`) |
| EnergyPlus, LibreCAD, LibreDWG ([components](#components), when installed) | `...\SAEngine\resources\energyplus`, `...\SAEngine\resources\librecad`, `...\SAEngine\resources\libredwg` (separate programs, with their licences) |
| Backend packages | `...\SAEngine\resources\python\Lib\site-packages` |
| Licences | `...\SAEngine\LICENSE.txt` (AGPL-3.0), `THIRD_PARTY_NOTICES.txt` (viewer bundles' npm packages, Python packages, source offers), `resources\app\ThirdPartyNotices.txt` (Code - OSS), `LICENSES.chromium.html` |
| Settings, logs | `%APPDATA%\SAEngine` |

### Which Python SAEngine uses

The analysis commands (*Run Analysis*, *Check Python Runtime*, results, design reports) start
Python in this order:

1. the setting **`saengine.python.path`**, when it is set;
2. in an installed SAEngine, the bundled `resources\python\python.exe`;
3. when SAEngine runs from the sources (`scripts\run-saengine.ps1`), the repository's `.venv`.

To use your own interpreter (for example to try a newer OpenSeesPy), open *File > Preferences
> Settings*, search for `saengine.python.path` and enter the full path of a Python **3.12**
x64 `python.exe` that has `saengine` and `opensees-studio` installed (OpenSeesPy 3.8's Windows
build only loads in Python 3.12). It is a setting of this machine only: a project folder's own
`.vscode/settings.json` cannot set it, so a project received from someone else never chooses the
program SAEngine starts. Clear the setting to go back to the bundled Python. Run
*SAEngine: Check Python Runtime* (F1) to see which interpreter and versions are in use.

The bundled Python is isolated from other Pythons on the machine: a `python312._pth` file next
to it fixes its module search path, so it ignores `PYTHONHOME`, `PYTHONPATH` and similar
variables (set by GIS software or another Python), and it never adds the per-user
site-packages (`%APPDATA%\Python\Python312\site-packages`, where `pip install --user` writes).
It does not load the `site` module either, so `.pth` files are not processed. Do not install
extra packages into it (an upgrade replaces the folder); to experiment, point
`saengine.python.path` at your own environment. A Python chosen with `saengine.python.path` is
not isolated this way.

## Building the installer

On a Windows x64 development machine with the repository set up as for development
(`npm install` in `workbench`, `packages\fem-viewer` and `packages\cad-editor` built,
`git submodule update --init` for `third_party\opensees-studio`):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-installer.ps1
```

The script checks the prerequisites and then:

1. builds the minified app with Code - OSS's own gulp tasks (`vscode-win32-x64-min`,
   `vscode-win32-x64-inno-updater`) into `<repo>\VSCode-win32-x64`;
2. downloads the pinned [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
   CPython 3.12.10 (`install_only_stripped`, SHA-256 checked) into
   `workbench\.build\saengine-installer\cache`, installs `opensees-studio` (headless, no GUI
   extras) and `saengine` into it from their **git-tracked** files only (an untracked module
   never ships) with every version pinned by `scripts\installer\constraints.txt`, stops when a
   tracked data file such as a Typst template was not installed (add it to
   `[tool.setuptools.package-data]`), prunes tests, caches, Tk and build-only files, isolates
   the interpreter (`python312._pth`, user site-packages off), precompiles the bytecode, checks
   that every backend module imports, that no Qt/VTK package is present and that a hostile
   `PYTHONHOME`/`PYTHONPATH`/user site-packages cannot shadow the bundle, and copies it to
   `VSCode-win32-x64\resources\python`;
3. writes `THIRD_PARTY_NOTICES.txt` (the npm packages, WebAssembly and fonts inside the
   viewer bundles, found from their source maps and `build.mjs`; every bundled Python package;
   each with its declared licence and licence texts; the AGPL source offer; the source offer
   for the copyleft binaries) and `LICENSE.txt`;
4. collects the upstream source archives of the copyleft binaries (gmsh, IfcOpenShell,
   cytriangle, web-ifc; pinned with SHA-256 in `scripts\installer\copyleft-sources.json`) into
   `dist\SAEngine-<version>-third-party-sources` (about 300 MB);
5. runs Inno Setup (`vscode-win32-x64-user-setup`, from the `innosetup` npm package in
   `workbench\node_modules`) and copies the result to
   `dist\SAEngine-x64-user-setup-<version>.exe` with a `.sha256` file. Each separate program
   that was bundled (`-EnergyPlusDir`, `-LibreCADDir`, `-LibreDWGDir`) becomes a setup
   component (`workbench\build\win32\code.iss`, `[Types]` and `[Components]`); without any, the
   setup has no *Select Components* page;
6. prints sizes and timings, with a table *Setup components (installed size)*: the core, each
   component, and a Compact and a Full install.

**Publishing.** Upload the setup, its `.sha256` file **and** the
`SAEngine-<version>-third-party-sources` folder to the same place (the same release page or
share). gmsh is GPL-2.0, IfcOpenShell and cytriangle LGPL-3.0, web-ifc MPL-2.0; they ship as
binaries, and offering their source from the same place as the setup is how the build meets
those licences. `THIRD_PARTY_NOTICES.txt` also carries a three-year written offer for that
source, made in the name of the SAEngine contributors (requests through GitHub issues).

Version naming: `-Version 0.0.26-beta` sets it. By default, a clean checkout of a release
commit (titled `v<x.y.z>`, or tagged so) gives `x.y.z`. Any other state is a pre-release of the
next patch: `x.y.(z+1)-dev.<commits since the release>`, plus `.local` when there are
uncommitted or untracked files (for example `0.0.26-dev.0.local`), so builds sort between
releases. Without any release in the history the `saengine` package version is used. Windows'
*Installed apps* and *About* still show the Code - OSS version from `workbench\package.json`,
1.142.0, because Inno Setup takes it from there.

Other switches: `-SkipAppBuild` (reuse
`VSCode-win32-x64`), `-SkipPython` (reuse the built Python), `-SkipSetup` (stop before Inno
Setup), `-RefreshConstraints` (re-pin `constraints.txt` from the development `.venv` after it
changed), `-NoPrecompile`, `-EnergyPlusDir` (bundle EnergyPlus 26.2.0), `-LibreCADDir` and
`-LibreCADLicenseDir` (bundle LibreCAD 2.2.1.6, an installed one such as
`C:\Program Files\LibreCAD` or its installer unpacked with `7z x`, with its licence texts;
`-LibreCADOnly -DryRun` tests that step alone), `-LibreDWGDir` and `-LibreDWGLicenseDir`
(bundle GNU LibreDWG 0.14's `dwg2dxf` from `libredwg-0.14-win64.zip` unpacked, with its
`COPYING`, for opening DWG drawings), `-AllowUnpinnedSources`, `-MinFreeGB`. The
release workflow passes all of them; see `docs/ci.md` for the release build, the pinned
downloads and the LibreCAD and Qt source offer.

After the app build the script replaces Code - OSS's launcher `bin\saengine.cmd` with the
SAEngine command line shim (`scripts\installer\saengine.cmd`) and keeps the launcher as
`bin\saengine-app.cmd`.

Then test the setup on the build machine without the repository's `.venv`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\installer\smoke-test.ps1
```

It installs silently into `%TEMP%\SAEngine-smoke\install`, analyses a one-bay frame with the
bundled Python under a hostile Python environment (`PYTHONHOME` pointing nowhere, a
`PYTHONPATH` and a user site-packages with a broken `numpy`), checking imports, the JSON-RPC
round trip, `opensees_studio.run` and equilibrium, runs the setup again as Compact (the
components' folders go, the backend reports them missing) and with `/COMPONENTS=` (they come
back), starts the installed SAEngine and checks over the DevTools protocol that the workbench renders,
the FEM viewer bundle loads and *Check Python Runtime* reports the bundled Python, then
uninstalls.

### Why python-build-standalone

The official embeddable zip has no `pip` and no `venv`, and its `._pth` file switches off
`site`; it needs patching before packages can be installed. python-build-standalone (used by
`uv`) is a complete,
relocatable CPython in one archive with a published SHA-256 per asset, so the bundle is built
with ordinary `pip install` and pinned by release, version and hash in
`scripts\installer\bundle-python.ps1`. The version matches the development `.venv` (3.12.10),
so the bundle runs the same binaries the tests pass on.

### Build notes

- Run time on the reference machine (16 GB RAM): about 15 minutes for the minified app,
  2 minutes for the Python bundle, 5 to 10 minutes for Inno Setup's LZMA compression.
- The gulp build runs with `scripts\installer\gulp-packaging-fixes.cjs` preloaded. It works
  around two problems of a local packaging run of this checkout without changing the shared
  build scripts: `npm ls` lists the dependencies of the linked `packages\*` folders as paths
  outside the workbench (the asar step cannot place them), and `build\.moduleignore` empties
  the locally compiled Copilot extension's `@github/copilot` folder that a later step needs
  (it is kept, minus the other-platform clipboard addons that `rcedit` cannot stamp).
  The file documents both; they belong in `build\lib\dependencies.ts` and
  `build\.moduleignore` eventually.
- A local build packages the built-in Copilot extension with all of its production
  `node_modules` (CI uses the VSIX instead). `build-installer.ps1` trims
  `resources\app\extensions\copilot\node_modules` to what the VSIX ships (`@github/copilot`,
  `@vscode/copilot-typescript-server-plugin`; `dist\extension.js` is a bundle). This saves
  about 200 MB. It also stops a failed install: nested `@opentelemetry` paths over 200
  characters pushed files past Windows' 260-character MAX_PATH, and Inno Setup failed with
  *MoveFile failed; code 3*. The script stops if any path inside the app is over 185 characters.
- The win32 packaging step calls `signtool.exe`. The script puts the newest x64 one from the
  Windows SDK (`C:\Program Files (x86)\Windows Kits\10\bin\<version>\x64`) on `PATH` when it
  is not there already; without the SDK's *Signing Tools for Desktop Apps* it stops.
- The packaged app goes to `<repo>\VSCode-win32-x64` (fixed by the Code - OSS build) and the
  setup to `<repo>\dist`; neither is committed.
- `workbench\build\win32\code.iss` carries three SAEngine changes: the licence page shows the
  repository's AGPL-3.0 `LICENSE`, the publisher is *SAEngine contributors* (not Microsoft),
  and the installer removes `resources\python` on upgrade and uninstall.

## Known issues

- **Unsigned installer and app.** Code signing is not set up, so SmartScreen warns on first
  run and some antivirus products may scan or quarantine `SAEngine.exe` or the bundled
  `python.exe`. Signing needs an Authenticode certificate (an EV certificate builds SmartScreen
  reputation immediately); Inno Setup's `SignTool` and the build's `--sign` hook are the
  places to wire it in.
- **No automatic updates.** The update service is not configured; install a newer setup over
  the old one (settings and projects are kept).
- **Size.** The bundled Python is about 600 MB on disk, mostly IfcOpenShell, gmsh, SciPy,
  typst and matplotlib (pulled in by sectionproperties/concreteproperties); the Jupyter
  packages that come with `rich[jupyter]` are installed too, because a dependency asks for
  them.
- **User setup only.** Only the per-user setup is built. A machine-wide (system) setup would
  install into `Program Files`, where Python cannot write bytecode caches; the bytecode is
  precompiled, so it should work, but it has not been tested.
- **OpenSeesPy licence: settle before distributing.** The licence shipped with openseespy
  and openseespywin 3.8.0.0 says OpenSeesPy is free for research, education and internal use,
  and that commercial redistribution of an application that uses it requires a separate
  licence (contact given in the licence text, in `THIRD_PARTY_NOTICES.txt`). Handing the
  installer to engineers outside your organisation may count as redistribution; get that
  licence or written clarification first. gmsh is GPL-2.0-or-later and IfcOpenShell
  LGPL-3.0-or-later (both shipped unmodified); `THIRD_PARTY_NOTICES.txt` lists every bundled
  package with its declared licence.
- **Triangle licence.** cytriangle (pulled in by sectionproperties) contains J. R. Shewchuk's
  Triangle, whose licence allows distribution as part of a commercial system only by direct
  arrangement with the author. Settle it together with the OpenSeesPy licence.
- **Copyleft source archives are upstream tarballs.** The archives in
  `SAEngine-<version>-third-party-sources` are the upstream releases matching the shipped
  versions. GitHub's tag archives leave out git submodules, and the PyPI wheels were built by
  their projects with their own build scripts; for a complete "corresponding source", ask the
  projects for their wheel build recipes or answer requests under the written offer.
