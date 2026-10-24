# SAEngine CI and releases

SAEngine's own repository has two GitHub Actions workflows in `.github/workflows/`. Code - OSS's
workflows in `workbench/.github/workflows/` belong to the imported upstream sources and never
run: GitHub only reads the repository root's `.github`.

| Workflow | Runs on | Trigger | What it does |
|---|---|---|---|
| `ci.yml`, job `python` | `ubuntu-latest` | push to `main`, `feat/**`, `fix/**`; pull requests to `main` and `feat/**`; manual | ruff (lint and format) on `python/` and `scripts/`; the workflow check and the tests of the CI scripts; `pytest` on `python/`; the verification pack quick run, checked against the expected failures; uploads `verification.json` and the Verification Manual PDF |
| `ci.yml`, job `workbench` | `ubuntu-latest` | as above | `npm ci` (cached), the viewer packages built, `tsc` typecheck, ESLint on the SAEngine sources, `transpile-client`, the SAEngine unit tests in Electron under xvfb |
| `release.yml` | `windows-latest` (or `vars.SAENGINE_RELEASE_RUNNER`) | tag `Pre-Alpha-v*`; manual (with a tag: a release; without: a test build) | the full installer with EnergyPlus, LibreCAD and LibreDWG from pinned downloads (cached), the smoke test, the Verification Manual, the setup, `.sha256` and sources zip as an artefact, and for a tag a **draft** GitHub pre-release (never published by the workflow); see [release.md](release.md) |

Both CI jobs run in parallel. A newer push to the same branch or pull request cancels the run
it supersedes (`concurrency` with `cancel-in-progress`). A release run is never cancelled by
another one for the same tag; the second one waits.

## What CI checks

**Python** (`python` job). The backend is installed as the installer installs it:
`pip install -c scripts/installer/constraints.txt -e third_party/opensees-studio -e "python[dev]"`,
so CI tests the pinned versions that ship. The Linux wheels of OpenSeesPy (openseespylinux) and
gmsh exist; the gmsh wheel needs a few X libraries, which the job installs. EnergyPlus is not
installed on CI: its tests skip themselves (`needs_energyplus`), and the verification case AH1
reports itself skipped. `third_party/opensees-studio` is vendored (its files are tracked in
this repository; there is no `.gitmodules`), so a plain checkout has it.

`python/tests/test_library.py` already fails when the generated
`projectLibraries.generated.ts` is out of date, so the library export needs no separate step.

**Verification pack.** `python -m saengine.verification --fast --pdf --out $RUNNER_TEMP/verification`
runs every fast case. Its exit code is 1 as long as a known issue fails, so the CI step ignores
it (`|| true`; the release workflow likewise) and the next step decides:
`scripts/ci/check_verification.py` compares `verification.json` with
`scripts/ci/verification-expected-failures.json` and fails when

- a case reports an error,
- a quantity fails that the list does not name,
- a listed case or quantity is no longer in the result (a stale entry: the case was dropped or
  renamed; both workflows run the whole pack, so a missing case is never just "not selected"), or
- the list differs from `KNOWN_ISSUES` in `python/tests/test_verification.py` (the same list
  is checked in two places, so both must change together).

A listed quantity that now passes is reported as a notice and accepted. The job summary shows
every case with its largest deviation.

The expected failures at the time of writing (see `docs/verification/README.md`, "Known issues"):

| Case | Quantity | Why |
|---|---|---|
| A9 | Tip deflection, default 1000 mm mesh | Linear tetrahedra are stiff in bending: about 8 % low |
| A9 | Tip deflection, 100 mm mesh (finest allowed) | The same, at the finest mesh Project Settings allow |

To change the list, edit both `scripts/ci/verification-expected-failures.json` and
`KNOWN_ISSUES`, and say why in the case's notes and the verification README.

**Workbench** (`workbench` job). `npm ci` of a Code - OSS checkout installs about 50 package
folders and takes the longest. The job reuses Code - OSS's own `node_modules` cache tooling
(`build/azure-pipelines/common/computeNodeModulesCacheKey.ts` and
`.github/workflows/node_modules_cache/cache.sh`): the cache key is the hash of every
`package.json`/`package-lock.json`, and the archive is saved on pushes only (pull requests read
it). The workbench depends on the local packages `@saengine/fem-viewer` and
`@saengine/cad-editor` (`file:../packages/*`); `scripts/ci/link-saengine-packages.sh` keeps
them out of the archive and restores the symlinks, and the job builds both packages before
the typecheck, because the workbench imports their types from `dist/`. Then:

```sh
npx tsc --project ./src/tsconfig.json --noEmit --skipLibCheck
npm run eslint -- 'src/vs/platform/saengine/**/*.ts' 'src/vs/workbench/contrib/saengine*/**/*.ts' 'src/vs/workbench/services/saengine*/**/*.ts'
npm run transpile-client
npm run electron
xvfb-run -a bash ./scripts/test.sh --grep SAEngine
```

ESLint fails on warnings as well as errors (`build/eslint.ts`).

## Costs

The repository is private, so Actions minutes are billed against the account's monthly
allowance (2,000 minutes on GitHub Free, 3,000 on Pro and Team at the time of writing). Linux
minutes count once; Windows minutes count twice. Estimates (not yet measured on GitHub's
runners):

| Run | Wall time | Billed minutes |
|---|---|---|
| CI, `python` job | 20 to 60 min (the full pytest suite takes most of it; measure on the first run) | 20 to 60 |
| CI, `workbench` job, cache hit | 20 to 30 min (typecheck and transpile dominate) | 20 to 30 |
| CI, `workbench` job, cache miss (a lockfile changed) | 35 to 50 min | 35 to 50 |
| Release | 90 to 180 min on `windows-latest` | 180 to 360 |

So one push costs about 40 to 90 minutes, and a release about 3 to 6 hours of the allowance.
To spend less: push work-in-progress commits together (superseded runs are cancelled), and run
the workflows manually when a branch is ready instead of on every push (remove `feat/**` from
`on.push.branches`).

**Runner size.** The installer build runs gulp with an 8 GB heap and needs about 10 GB of disk.
GitHub's standard Windows runner for private repositories is small (2 vCPU and 7 GB of RAM at
the time of writing), so the minified build may run out of memory or be slow; the workflow
prints the free disk and the memory first. If it fails for that reason, create a larger runner
(Settings, Actions, Runners; billed per minute at a higher rate) and set the repository
variable `SAENGINE_RELEASE_RUNNER` to its label. Nothing else changes.

## Secrets

None beyond the `GITHUB_TOKEN` GitHub gives every run. `ci.yml` has `contents: read` (the
token only downloads Electron and the built-in extensions with a higher rate limit);
`release.yml` has `contents: write` to create the release. There is no signing certificate yet:
the setup is not code-signed.

## Cutting a release

The short version, the caches, test builds, the in-app update check and what is still manual:
[release.md](release.md). The details:

1. Make the release commit as before: a commit titled `v<x.y.z>` (for example `v0.0.35`). The
   release version is `<x.y.z>-alpha.<N>`, N from the tag. The commit bumps `x.y.z` in both
   `workbench/package.json` and `python/src/saengine/__init__.py` (`__version__`, which `.civil`
   archives and the `saengine` command report); `python/tests/test_version.py` fails when they
   differ.
2. Optional, in the same commit: a folder `docs/release/Pre-Alpha-v<N>/` with
   - `notes.md`, the release notes (`{version}` and `{sha256}` are filled in); without it a
     short default with the install steps and the file list is used;
   - `title.txt`, the release title (default `Pre Alpha Version <N>`);
   - any file to attach, such as `SAEngine Testing Guide.pdf`, `Sample.soil-report.json` or
     `Sample.MEP.model.ifc` (spaces become dots, as GitHub shows them). The Testing Guide is
     written by hand for each release, so it is only attached when it is there. Only synthetic
     test data belongs in this folder.
3. Push the commit, then the tag:

   ```sh
   git tag Pre-Alpha-v5
   git push origin Pre-Alpha-v5
   ```

   Or run "Release" from the Actions tab (workflow dispatch) with the tag name and
   "draft_release" ticked; there the version can be overridden. The release is always a draft.
4. The workflow builds `dist/SAEngine-x64-user-setup-<version>.exe` with
   `scripts/build-installer.ps1 -EnergyPlusDir ... -LibreCADDir ... -LibreCADLicenseDir ... -LibreDWGDir ... -LibreDWGLicenseDir ...`,
   runs `scripts/installer/smoke-test.ps1` on it, builds the Verification Manual with the
   bundled Python (checked against the expected failures), and creates the pre-release as a
   **draft** with:
   - `SAEngine-x64-user-setup-<version>.exe` and its `.sha256`,
   - `SAEngine-<version>-third-party-sources.zip` (the copyleft source archives),
   - `Sample.Frame.zip` (`workbench/resources/saengine/samples/Sample Frame`),
   - `SAEngine.Verification.Manual.pdf`,
   - the files of `docs/release/<tag>/`.
5. Review the draft on GitHub (Releases), try the setup, and publish it. Publishing creates the
   tag if the run was started by hand. The run fails instead of overwriting when a release for
   the tag exists already. The setup, its `.sha256` and the sources zip are also kept as the
   run artefact `SAEngine-setup-<version>` for 14 days.

The workflow keeps `THIRD_PARTY_NOTICES.txt`, the LibreCAD and LibreDWG bundle manifests, the sources
`README.txt`, the setup log and the release notes as the `release-logs` artifact for 14 days.

## Third-party programs in the release

`scripts/ci/fetch_pinned.py` downloads what `scripts/ci/third-party-binaries.json` lists and
refuses any file whose size or SHA-256 differs from the pin. A file already in the cache is
checked again, not trusted.

| Item | Version | Pin |
|---|---|---|
| EnergyPlus for Windows x64 (zip) | 26.2.0 | `15ab6988...4461e7` |
| LibreCAD installer `LibreCAD-v2.2.1.6-win64-msvc.exe` | 2.2.1.6 | `0cd876d0...4f95b`, GitHub's own `digest` of the release asset |
| LibreCAD's `LICENSE` and `licenses/gpl-2.0.txt` | 2.2.1.6 | sha256 of the files at the tag |
| Qt's `LICENSE.LGPLv3` and `LICENSE.GPL3` (qtbase) | 5.15.2 | sha256 of the files at the tag |
| GNU LibreDWG for Windows x64 `libredwg-0.14-win64.zip` | 0.14 | `1ad7e153...10fea8`, GitHub's own `digest` of the release asset (the GNU-signed release) |
| LibreDWG's `COPYING` (GPL-3.0 text) | 0.14 | sha256 of the file at the tag |

To bump one, change url, file, size and sha256 together. For a GitHub release asset, the hash
is the `digest` field of `GET /repos/<owner>/<repo>/releases/tags/<tag>`.

**LibreCAD** is GPL-2.0-only. SAEngine ships it as a separate program in `resources\librecad`
and starts it as its own process with a DXF path (an aggregate, never linked; the "Open in CAD"
action falls back to Windows' own DXF handler when it is not bundled). The NSIS installer is
unpacked with the 7-Zip preinstalled on GitHub's Windows runners (`7z x`);
`scripts/installer/librecad_bundle.py` copies the program folder without the installer's
`$PLUGINSDIR` and uninstaller, adds the licence texts to `resources\librecad\licenses` (LibreCAD's
installer ships none: its licences are compiled into the program) and writes
`resources\librecad\SAENGINE-BUNDLE.json` with the LibreCAD and Qt versions from the version
resources of `LibreCAD.exe` and `Qt5Core.dll` and the Qt modules whose DLLs it ships.
`THIRD_PARTY_NOTICES.txt` gets a LibreCAD section with those texts.

**Its Qt.** LibreCAD 2.2.1.6's Windows build is made with Qt 5.15 (MSVC 2019, 64-bit), whose
DLLs it links dynamically under the LGPL-3.0. LibreCAD's own release publishes neither a Qt
source archive nor an offer for one. SAEngine distributes those DLLs, so it takes on the
LGPL-3.0's source obligation itself: `fetch-sources.ps1` puts the Qt source archive of every
Qt module the bundle ships (`qtbase`, `qtsvg`, `qtimageformats`, `qttools` are listed in
`copyleft-sources.json`; a module without an entry fails the build) next to LibreCAD's own
source into the third-party sources, and the notices name the Qt version and link to
`download.qt.io`. Pointing to Qt's servers alone would be weaker: the GPL-3.0 section 6(d),
which the LGPL-3.0 uses, leaves the distributor responsible for the source staying available.

**GNU LibreDWG** is GPL-3.0-or-later. Its `dwg2dxf` converts the architects' DWG drawings to
DXF for the floor plan's underlays and the geometry import (`saengine.library.dwg`); SAEngine
ships it as a separate program in `resources\libredwg` and the backend runs it as its own
process (an aggregate, never linked; without it a DWG is refused with a message asking for the
drawing as DXF). `scripts/installer/libredwg_bundle.py` copies only `dwg2dxf.exe` and
`libredwg-0.dll` from the official Windows zip (the iconv and PCRE2 DLLs serve only `dwggrep`),
adds LibreDWG's `COPYING` (the zip ships no licence file), runs `dwg2dxf --version` from the copy
and writes `resources\libredwg\SAENGINE-BUNDLE.json`. Its source, `libredwg-0.14.tar.xz` from
`ftp.gnu.org` (byte-identical to the GitHub release asset), is pinned in
`copyleft-sources.json` and collected with `-LibreDWGManifest`. ODA File Converter is not an
option: its licence forbids redistributing it.

**Pinning the source archives.** GitHub does not publish hashes of its tag tarballs, and the Qt
archive publishes md5 sums only, so a new LibreCAD or Qt source entry in
`copyleft-sources.json` may start with `"sha256": null`. `fetch-sources.ps1` refuses such an
entry unless it runs with `-AllowUnpinned` (`build-installer.ps1 -AllowUnpinnedSources`). It then
downloads the archive, writes its hash into the sources `README.txt` (marked "not pinned in this
build") and prints a `::warning::` with the hash: copy it into `copyleft-sources.json`. Every
entry is pinned today, so `release.yml` no longer passes the flag: an unpinned entry fails the
release build.

## The installer additions

- **`bin\saengine.cmd`**: the SAEngine command line (`python -m saengine.cli`, see
  `docs/cli.md`), run with the bundled Python in isolated mode
  (`"%~dp0..\resources\python\python.exe" -I -m saengine.cli %*`). `bin\saengine` is the same
  for Git Bash. Code - OSS's launcher, which opens a folder or file in the SAEngine window, moves
  to `bin\saengine-app.cmd` (`build-installer.ps1` does this after the app build;
  `workbench/build/win32/code.iss` installs both). The app itself still calls
  `bin\saengine.cmd --file-write <args>` (with `--file-chmod` first when unlocking) for "Retry as
  Admin" saves (`nativeHostMainService.writeElevated` uses `bin\<applicationName>.cmd`), so the
  shim hands a first argument `--file-write` or `--file-chmod` on to `saengine-app.cmd`; every
  other call is the Python command line.
- **"Add the saengine command to PATH"**: the setup's existing PATH task (Code - OSS's
  `addtopath`, which adds `{app}\bin` and removes it on uninstall), renamed and now unchecked by
  default.
- **`.civil` file association** under "Register SAEngine as an editor for supported file types"
  (checked by default): double-clicking a `.civil` project archive starts
  `SAEngine.exe "<path>.civil"`.

## Checking the workflows locally

```sh
.venv/Scripts/python -m pip install PyYAML actionlint-py   # MIT; dev tools, not shipped
.venv/Scripts/python scripts/ci/check_workflows.py        # structure, pins, paths, then actionlint
.venv/Scripts/python -m pytest -q scripts/ci/tests        # the CI and installer helper scripts
.venv/Scripts/python -I scripts/ci/fetch_pinned.py --verify <EnergyPlus zip> --name energyplus
powershell -ExecutionPolicy Bypass -File scripts/build-installer.ps1 -LibreCADOnly -DryRun -LibreCADDir "C:\Program Files\LibreCAD"
```

`check_workflows.py` checks that every workflow parses, has triggers, `permissions` and
`concurrency`; that every job has `runs-on`, `timeout-minutes` and steps; that every action is
pinned to a full commit SHA; that the repository scripts a step runs exist; and that no secret
other than `GITHUB_TOKEN` is used. CI runs it without actionlint.
