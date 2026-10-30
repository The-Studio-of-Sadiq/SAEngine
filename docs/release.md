# Releasing SAEngine

SAEngine is released as GitHub pre-releases, "Pre Alpha Version N" with the tag
`Pre-Alpha-vN`. The Windows x64 user setup is built by `.github/workflows/release.yml` on a
GitHub Windows runner, with the same script as on a PC (`scripts/build-installer.ps1`). The
workflow never publishes anything: it builds, tests and, for a release tag, creates a **draft**.
A person publishes it. Costs, runner size and the third-party pins: [ci.md](ci.md).

## What the workflow does

| Step | Detail |
|---|---|
| Version | `scripts/ci/release.py version`: `<x.y.z>-alpha.<N>` from the release commit `v<x.y.z>` and the tag; a test build (no tag) is `<x.y.z>-ci.<run number>` |
| Third-party programs | `scripts/ci/fetch_pinned.py` downloads EnergyPlus 26.2.0, LibreCAD 2.2.1.6 and LibreDWG 0.14 and the licence texts listed in `scripts/ci/third-party-binaries.json`, checks size and SHA-256 and unpacks them. Nothing comes from a PC's local folders |
| Viewer packages, workbench `npm ci` | as Code - OSS's Windows CI (preinstall first, three attempts) |
| Installer | `build-installer.ps1 -Version ... -EnergyPlusDir ... -LibreCADDir ... -LibreDWGDir ...` with the licence folders. The copyleft source archives (`scripts/installer/copyleft-sources.json`) and CPython (`bundle-python.ps1`) are pinned with SHA-256 too; an unpinned or changed file fails the build |
| Smoke test | `scripts/installer/smoke-test.ps1`: silent install, bundled Python, app start, uninstall |
| Verification Manual | with the bundled Python, checked against the expected failures |
| Artefact | `SAEngine-setup-<version>`: the setup, its `.sha256` and `SAEngine-<version>-third-party-sources.zip`, kept 14 days |
| Draft release | only for a tag push, or a dispatch with a tag and "draft_release" ticked. Always `--draft`; fails if a release for the tag exists |
| Logs | `release-logs`: notices, bundle manifests, sources README, setup log, release notes |

**Downloads never hang.** A release build once hung for three hours on a stalled Qt source
download. Every download now has a connect timeout, a minimum speed and retries:
`fetch_pinned.py` (60 s socket timeout, abandoned below 50 kB/s over 2 minutes, 4 attempts
with growing pauses) and, for the PowerShell scripts, `scripts/installer/download.ps1`
(`curl.exe --connect-timeout 30 --speed-limit 50000 --speed-time 120 --max-time 7200 --retry 4
--retry-all-errors`). The long steps also have their own `timeout-minutes`.

### Caches

| Cache | Key |
|---|---|
| Pinned downloads (EnergyPlus, LibreCAD, LibreDWG, licence texts, copyleft source archives, CPython) | the two manifests and `bundle-python.ps1`. Restored files are re-checked against their SHA-256 |
| pip wheels of the bundled backend | `constraints.txt` and the two `pyproject.toml` |
| Electron download (`%LOCALAPPDATA%\electron\Cache`) | `workbench/.npmrc` and `build/checksums/electron.txt`, as Code - OSS's own `setup-electron` action |
| Workbench `node_modules` (7-Zip archive, Code - OSS's `node_modules_cache/cache.ps1`) | `computeNodeModulesCacheKey.ts win32 x64` (every package.json and lock file). `node_modules/@saengine/*` junctions are left out and made again |
| Built-in extensions | `computeBuiltInDepsCacheKey.ts` |

GitHub scopes caches by ref: a run restores caches saved by its own branch or tag and by the
default branch (`main`). So test builds by hand on one branch share their caches, but a tag
push (its own ref) only finds what `main` saved. The cheapest way to cut a release is
therefore a **dispatch on the release branch with the tag filled in** (below), which reuses
that branch's caches. The repository's cache limit is 10 GB; the node_modules archive is the
largest entry (1 to 2 GB).

## Cutting a release

1. Make the release commit, titled `v<x.y.z>`, which bumps `x.y.z` in `workbench/package.json`
   and `python/src/saengine/__init__.py`. Optionally add `docs/release/Pre-Alpha-v<N>/` with
   `notes.md`, `title.txt` and files to attach (see [ci.md](ci.md), "Cutting a release").
2. Push it. Then either
   - **Actions, Release, Run workflow** on that branch with tag `Pre-Alpha-v<N>` and
     "draft_release" ticked (reuses the branch's caches), or
   - push the tag: `git tag Pre-Alpha-v<N>` then `git push origin Pre-Alpha-v<N>`.
3. Wait for the run (90 to 180 minutes on `windows-2022`). Download the
   `SAEngine-setup-<version>` artefact or open the draft under Releases, install it on a test
   PC and check it.
4. **Publish the draft by hand** on GitHub. Publishing a dispatched draft creates the tag on
   the built commit. Only published releases are visible to the in-app update check.
5. Refresh the module mirrors from the release commit (`docs/marketplace-plan.md`, "Code
   modules"): `python -I scripts/modules/mirror.py --list`, then
   `python -I scripts/modules/mirror.py <id> --push` for each.

A **test build** (no release): Run workflow with the tag empty. It builds, smoke-tests and
uploads the artefact; nothing is released. Each run costs 180 to 360 Windows-billed minutes, so
run it only when the installer or the workflow changed.

## Setup components

The release build bundles EnergyPlus, LibreCAD and LibreDWG, so its setup has the *Select
Components* page (`[Types]` Full, Compact, Custom and `[Components]` in
`workbench/build/win32/code.iss`; [install/README.md](install/README.md#components)). Full is
the first type: a new install, attended or silent, gets everything, and an update keeps what
was chosen before. The build log's table *Setup components (installed size)* gives the size
of the core and of each component; copy it into the release notes when it changed.

*Add Component...* in the app re-runs the setup of the installed version with
`/COMPONENTS=`. It needs that version's setup **and** its `.sha256` from the release page (the
user puts both in one folder), so both stay release assets. The app never downloads the setup
for this (decision D7 of [marketplace-plan.md](marketplace-plan.md)): it asks for the file,
checks the SHA-256 in the shared process (`IFemSolverService.runSetup`) and starts it. Once the
setup is code-signed, that check should also verify the Authenticode signature (round M7).

The smoke test runs the setup again as Compact and with `/COMPONENTS=` and checks that the
components' folders go and come back.

## In-app update check

Help, **Check for SAEngine Updates...** (also in the Command Palette), and once at start-up
30 seconds after the window opens unless `saengine.update.checkOnStartup` is off. The start-up
check runs only in an installed build, never from sources.

1. Reads `product.json` `saengineUpdate.releasesUrl`
   (`https://api.github.com/repos/The-Studio-of-Sadiq/SAEngine/releases?per_page=20`). No token,
   no data is sent beyond the request itself.
2. Picks the newest published release (drafts are never seen; pre-releases count) whose assets
   include `SAEngine-x64-user-setup-<version>.exe` **and** its `.sha256`, and whose version is
   newer than the running build (SemVer order: `0.0.42-alpha.5` < `0.0.42-alpha.10` <
   `0.0.43-alpha.1`). The running version is `saengineVersion`, which `build-installer.ps1`
   stamps into the packaged `product.json`; a build from sources uses `package.json`'s.
3. At start-up a notification offers *Release Notes and Download...*, *Skip This Version* and
   *Don't Check on Start-up*. The manual check also reports "up to date" and errors.
4. The dialog shows the release notes. Only **Download...** downloads: the user picks where
   (default: Downloads), the `.sha256` file is read first, the setup is downloaded and its
   SHA-256 compared (Code - OSS's checksum service). A mismatch deletes the file.
5. *Run Setup* starts the setup the user just downloaded; it asks to close SAEngine. Nothing is
   installed silently.

Code - OSS's own update service is not used: it needs an update server answering per commit
(`updateUrl`) and installs in the background. With no `updateUrl` in `product.json` it stays
disabled and its menu entries hidden, so there is one update check, in
`workbench/src/vs/workbench/contrib/saengineUpdate/`. The version comparison and checksum
parsing are in `common/updateCheck.ts` with unit tests (`--grep "SAEngine - update check"`).

**While the repository is private** the releases API answers 404 without a token, so the check
reports "the repository may not be public yet" (manual) or stays silent (start-up). It works
as soon as the repository is public.

## Still manual

- **Publishing** the draft release (by design).
- **Code signing.** The setup is unsigned: SmartScreen warns, and Smart App Control may block
  it. SignPath (free for open-source projects) is planned once the repository is public. The
  hooks are in place: `build-installer.ps1` calls the script named by `SAENGINE_SIGN_HOOK`
  with `-Stage app -Path <app folder>` before Inno Setup and `-Stage setup -Path <setup>` before
  the `.sha256` is written, and the workflow has a marked "Code signing (not yet)" step where
  the SignPath action (upload the unsigned artefact, receive the signed one) goes. Once signed,
  the update check should also verify the Authenticode signature before offering *Run Setup*.
- The Testing Guide PDF in `docs/release/<tag>/`, written for each release.
- Bumping a pin: change url, file, size and sha256 together in the manifest (ci.md).
