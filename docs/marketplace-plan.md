# Marketplace and modular install: plan

Status: **in progress** (plan of 2026-10-30, updated 2026-11-01). Round M1 (manifest and registry
kinds) is built: `kind`, `requires`, `contents`, `preview` in `pack.json`, per-kind discovery, no
programs in a package, `saengine codepack --kind` (alias `saengine package`); see
docs/code-packs.md, "Other package kinds". M2 (package repositories and index) is in pull requests
in those repositories, M3 (the Packages page) and M6 (installer components) are built; see "Built
in M…" in §6 and §8 for each. Decisions D1–D11 are
in §9: four are settled by the owner, the others follow the stated recommendation until the owner
says otherwise.

Two goals:

1. **A marketplace** of add-ons that a user finds, installs, updates and removes from inside
   SAEngine, published from separate repositories: *design codes*, *structure templates*
   (special structures: trusses, domes, vaults, bridges…) and *building templates* (ordinary
   buildings with floor plan and BIM).
2. **A modular installer**: a small core setup, with the large optional programs (EnergyPlus,
   LibreCAD, LibreDWG…) chosen at install time or added later, instead of one large setup.

Ground rules this plan keeps:

- **One package format.** The design code pack (`pack.json`, `docs/code-packs.md`) already has
  a manifest, a registry with scopes and shadowing, inheritance, zip install, validation and a
  hash-keyed trust model for Python. Every marketplace item reuses that format and that
  registry. There is no second manifest, no second registry, no second trust store.
- **No duplication.** Each feature keeps one owner: the Code Packs page becomes the place where
  every package is listed and installed; the New Building wizard, the modeller's Generate panel
  and Project Settings → Design code *link* to it rather than growing their own installers.
- **Data first, code only with trust.** A package that is only data installs and works with no
  questions. A package with Python (`hooks`) never runs it until the user trusts that exact
  code, as code packs do today. The marketplace never grants trust.
- **Nothing executable is downloaded unverified.** Every download is pinned by SHA-256 in a
  signed index; programs (`.exe`, `.dll`) only ever come with the setup or as Authenticode-signed
  component installers.

## 1. What exists today

| Piece | Where | What it gives the marketplace |
| --- | --- | --- |
| Pack manifest `saengine.codePack/1` | `python/src/saengine/codes/manifest.py` (`PackManifest`), schema in `codes/schemas/` | id pattern, name, version, country/region, `extends`, `sources`, `licence`, `author`, `hooks` |
| Registry | `codes/registry.py` (`Registry`) | discovery in three scopes (project > user > built-in, plus "folder" for validate), shadowing report, inheritance chain, problems instead of exceptions, cached by file signature, `install()` from folder or `.zip` with safe extraction and copy-then-swap |
| Trust | `codes/trust.py` (`TrustStore`) | `%APPDATA%\SAEngine\code-pack-trust.json`, keyed by pack id + SHA-256 of all `.py` files of the pack; any edit revokes trust; built-in always trusted; the hashed bytes are the bytes executed |
| Authoring | `codes/template.py`, `saengine codepack new/validate/diff/show/list` (`cli/codepack.py`) | skeleton, validation usable in CI (exit code 1 on error), diff against the parent |
| UI | `saengineLibrary/browser/codePacksEditor.ts` (≡ → Code Packs…) | list with scope badges, details, Install Code Pack… (folder or zip, user or project), New, Validate, Trust |
| Parametric shapes | `library/shapes.py`: `SpaceTruss`, `PlaneTruss`, `Arch`, `Dome`, `BarrelVault`, `CableNet` (`SHAPES`, `ShapeInput`, `shape_geometry`, `insert`); starting values in `library/templates.py` `_SHAPES`; RPC `shape_geometry`; scripts (`library/script.py`) | the engine that structure templates drive |
| Building generator | `library/generator.py` `BuildingSpec` → `generate_building`; wizard form `saengineProject/browser/newBuildingModel.ts` (`DEFAULT_FORM`: 3×6 m by 2×5 m, 6 storeys, Dhaka, SD, residential) | the engine that "spec" building templates drive. There are no named presets yet: `DEFAULT_FORM` is the only one |
| Project archive `.civil` | `project/archive.py` (inputs: soil, settings, materials, objects, floor plan, structural model, BIM, MEP, substructure; results optional) | the container that "full" building templates reuse |
| Pinned downloads (build time) | `scripts/ci/third-party-binaries.json` + `scripts/ci/fetch_pinned.py`; `scripts/installer/download.ps1`, `copyleft-sources.json`, `bundle-python.ps1` | url + size + SHA-256 per file, mismatch fails; the same discipline is reused for the index and the components |
| Update check | `saengineUpdate/common/updateCheck.ts` (GitHub releases API of the SAEngine repo) | the place that already talks to GitHub from the app: the index fetch sits beside it |
| Installer | Inno Setup (`workbench/build/win32/code.iss`), `scripts/build-installer.ps1`; `[Tasks]` only (icons, context menu, PATH), **no `[Components]` yet**; per-user setup only; unsigned | the starting point of the modular installer |

More detail on the installer and the bundled programs:

- `scripts/build-installer.ps1` runs the gulp `vscode-win32-x64-min` build, then adds Python,
  EnergyPlus, LibreCAD and LibreDWG, writes the notices and builds the user setup
  `dist\SAEngine-x64-user-setup-<version>.exe` with its `.sha256`. Optional parts exist only at
  build time today: `-EnergyPlusDir`, `-LibreCADDir`, `-LibreDWGDir` decide whether each one is
  bundled. `code.iss` copies the whole app folder with one `Source: "*"` line.
- The app already finds each program and works without it, in a reduced way:

  | Program | Lands in | Found by | Without it |
  | --- | --- | --- | --- |
  | EnergyPlus 26.2.0 | `resources\energyplus` | `hvac/energyplus.py` `find_energyplus` (env `SAENGINE_ENERGYPLUS`, then bundled) | HVAC uses its estimate |
  | LibreCAD 2.2.1.6 | `resources\librecad` | `platform/saengine/node/femSolverService.ts` `findCadProgram` (setting, bundled, `%ProgramFiles%`) | "Open in CAD" uses the system's DXF program |
  | LibreDWG 0.14 | `resources\libredwg` | `library/dwg.py` `find_converter` (env `SAENGINE_LIBREDWG`, then bundled) | DWG must be saved as DXF first |
  | QGIS | not bundled | `gis/site.py` `qgis_program` | site exchange off |

- Signing: `build-installer.ps1` has a `SAENGINE_SIGN_HOOK` (stages `app` and `setup`) and
  `release.yml` has a placeholder step for SignPath. Nothing is signed yet.
- Reusable download code: `scripts/ci/fetch_pinned.py` (Python: download with stall timeout and
  retries, size + SHA-256 verify, safe unpack, tested) and, in the workbench, the update check's
  `IDownloadService` + `IChecksumService` use and `updateCheck.ts` `parseSha256File` /
  `checksumMatches`. The update check polls
  `api.github.com/repos/princekhan7748/saengine/releases` (`workbench/product.json`
  `saengineUpdate.releasesUrl`, also `code.iss`): it must follow the repository transfer.
- Workbench features are core contributions (`contrib/saengine*`, statically imported), not VS
  Code extensions; the only SAEngine extensions are `theme-saengine` and
  `saengine-language-pack-bn`. The VS Code extension gallery is therefore *not* the vehicle for
  packages: packages are data the Python registry reads.

## 2. One manifest for every package

`pack.json` stays the manifest. It gains **one required-by-default field, `kind`**, and a few
optional fields; a pack without `kind` is a design code pack, so every existing pack (BNBC 2020,
users' packs) stays valid unchanged.

```jsonc
{
  "schema": "saengine.codePack/1",          // unchanged; the schema id is not renamed (D9)
  "kind": "structureTemplate",              // designCode (default) | structureTemplate | buildingTemplate
  "id": "warren-roof-trusses",
  "name": "Warren roof trusses",
  "version": "1.2.0",
  "author": "…", "licence": "CC-BY-4.0",
  "country": null,                          // design codes and building templates: ISO 3166
  "description": "…",
  "sources": [ … ],                         // as today
  "extends": null,                          // design codes only (inheritance of tables)
  "requires": {                             // new, optional
    "saengine": ">=0.0.50",                 // the lowest app version that understands the package
    "packages": { "bnbc2020": ">=1.0.0" }   // other packages it needs (a building template's code)
  },
  "contents": [ "templates/*.json" ],       // new: files of the kind (data/*.json for designCode)
  "preview": "preview.png",                 // new, optional: card image in the marketplace
  "hooks": null                             // as today: Python, runs only when trusted
}
```

What changes in code (round M1):

- `PackManifest` gets `kind`, `requires`, `contents`, `preview` (all optional; `kind` defaults to
  `designCode`). `PackInfo` carries `kind`.
- `Registry` discovers **per kind**: one class, one cache, one trust store, and a folder per kind
  in each scope, so no existing path moves:

  | Scope | designCode | structureTemplate | buildingTemplate |
  | --- | --- | --- | --- |
  | built-in | `saengine/codes/packs/` | `saengine/codes/packs/` (one built-in package of the six shape presets) | — |
  | user | `%APPDATA%\SAEngine\code-packs\` | `%APPDATA%\SAEngine\packages\structure-templates\` | `%APPDATA%\SAEngine\packages\building-templates\` |
  | project | `02 Project Settings/code-packs/` | — (a template is *applied*: its geometry is copied into the model) | — (applied: copied into the project) |

  (D9: alternatively move everything to one `packages\` folder now, with a one-time migration
  of `code-packs\`; recommended to keep the current folders, since projects and docs name them.)
- `Registry.install()` already validates and swaps atomically; it learns to check `requires`
  (refuse a package that needs a newer SAEngine, offer to install missing required packages).
- `saengine codepack …` becomes the CLI for every kind (`--kind`), with `saengine package` as an
  alias; `validate` validates templates against their models.

### Item kinds

**Design codes (`designCode`).** Exactly today's code packs. The marketplace adds discovery and
updates; packs keep `extends`, tables, clauses and trust. Regional packs (e.g. a coastal
Bangladesh wind pack that extends `bnbc2020`) are the expected first community items. The known
limits in `docs/code-packs.md` (member design, generator and soil not yet following the pack)
must be stated on every design-code card until they are lifted: a user must not believe an
installed pack changes the member design when it does not.

**Language packs (`languagePack`).** Decided with track T48 (2026-11-01): a data package, like
every other kind, never a VS Code extension from a gallery. `pack.json` gives `language` (BCP 47);
`messages/*.json` hold the labels of the reports and drawings (English text → translation),
merged over the built-in catalogue of `saengine.i18n`; `ui/*.i18n.json` hold screen strings in
the workbench's language-pack format (validated now; applied to the screens in a later round, by
writing a language-pack extension into the user's extensions folder). Installed for the user
only. The format is in docs/packages.md, "Language pack".

**Structure templates (`structureTemplate`).** Two levels:

1. *Presets of a built-in shape* (data only): a JSON file per template that is a `ShapeInput`
   with named parameters, e.g. `{"name": "Warren truss 24 m", "shape": {"kind": "planeTruss",
   "span": 24000, "depth": 2400, "panels": 8, "pattern": "warren", "memberType": "MEMBER"}}`.
   Validated by the existing `ShapeInput` model; applied through the existing Generate panel and
   `shape_geometry` → `insert`. No new code path.
2. *New shape kinds* (bridges, towers, hypar, geodesic domes…): need a generator, which is
   Python. The package names it in `hooks` (a function `local(params) -> Geometry` plus a JSON
   Schema of its parameters), runs only when trusted, and its geometry still enters the model
   through `insert()`. This is the same trust path as code-pack hooks; it is a later round (M5).

The six shapes in `library/shapes.py` stay in core as the engine (scripts, the RPC, the schema
export and the tests depend on them). What becomes the *first marketplace item* is a package
`saengine-shapes` holding their presets (today's `_SHAPES` starting values plus a few named
variants), shipped built-in and also published in the index, so the marketplace has content on
day one and the built-in copy can be updated from it (D5).

**Building templates (`buildingTemplate`).** Two levels, matching the two ways a building
starts today:

1. *Spec templates* (data only): a `BuildingSpec` JSON (grids, storeys, system, materials,
   location, use), e.g. "Dhaka 6-storey residential, 3×2 bays", "G+9 apartment with lift core".
   Applied by the New Building wizard: it prefills the form; the generator does the rest. These
   are the "generator presets" the owner asked for: `DEFAULT_FORM` becomes the first of them.
2. *Full templates*: an inputs-only `.civil` archive (floor plan, architecture layer, BIM, MEP
   inputs, settings; never results, never soil reports) plus `pack.json` and a preview. Applied
   by **New Project from Template…**, which is the existing archive-open path with "open as a
   new project". Requires the design code package it was built on (`requires.packages`).

A building template never contains client data. The index repository's CI rejects archives with
a soil report, a site location more precise than a town, or names in `author` fields of
drawings other than the template's author.

## 3. Index and repositories

Decided (D2, 2026-10-30): **one repository per kind**, plus a small index repository that
merges them. Names under the organisation (D1; `<org>` is the GitHub login of "studio of
sadiq", fixed once the transfer is done):

```
<org>/saengine-design-codes           <id>/pack.json, data/…            (kind designCode)
<org>/saengine-structure-templates    <id>/pack.json, templates/…, preview.png
<org>/saengine-building-templates     <id>/pack.json, template.civil | spec.json, preview.png
  each: .github/workflows/ validate on every PR; on a tag, zip the changed packages, hash them
        and attach them to an immutable GitHub Release; CODEOWNERS for packages with hooks

<org>/saengine-index                  the one index the app reads
├── sources.json                      the three kind repositories (and, later, community entries)
├── scripts/build_index.py            reads each source's latest release manifest, checks every
│                                     zip's size and SHA-256, writes index.json
└── .github/workflows/                runs on a dispatch from the kind repositories; the owner
                                      signs index.json (offline key) and publishes the release
```

The validator, the CI workflow and `build_index.py` are shared: the kind repositories use one
reusable workflow from `saengine-index` so the three never drift apart.

- **CI on every PR** (in each kind repository) runs `saengine codepack validate --kind … <dir>` for each changed package
  (the SAEngine CLI from the latest release, installed from the release's Python wheel), checks
  licences are present and SPDX, previews are small, archives are inputs-only, and that no
  package with `hooks` is merged without a second reviewer (CODEOWNERS).
- **Publishing**: a tag in a kind repository builds `<id>-<version>.zip` for every changed
  package and attaches them to a GitHub Release; `saengine-index` then writes **`index.json`**
  and `index.json.sig` as assets of its own release, and the app reads the latest of those.
  Releases are immutable, so a pinned hash never changes under a URL.
- **Community packages** (decided D10: not in the first release; after round M5): an author adds
  an entry to `saengine-index/sources.json` by PR with the URL of a release asset in their own
  repository and its SHA-256 (the winget / Homebrew-tap model): the author keeps their
  repository, the index pins exactly the reviewed file, and a new version is a new PR.

`index.json` (one entry per package version the app may install):

```jsonc
{
  "schema": "saengine.packageIndex/1",
  "generated": "2026-11-15T10:00:00Z",
  "packages": [{
    "id": "bd-coastal-wind", "kind": "designCode", "name": "…", "version": "1.0.0",
    "country": "BD", "author": "…", "licence": "CC-BY-4.0",
    "requires": { "saengine": ">=0.0.50", "packages": { "bnbc2020": ">=1.0.0" } },
    "url": "https://github.com/…/releases/download/packages-2026-11-15/bd-coastal-wind-1.0.0.zip",
    "size": 48211, "sha256": "…",
    "hooks": false, "hooksSha256": null,          // the code hash the trust store will see
    "preview": "…png url…", "previewSha256": "…",
    "source": "official"                           // official | community
  }]
}
```

## 4. Trust and download safety

Layered, and every layer exists or is small:

1. **The index is signed** with an Ed25519 key held by the owner (D3). The app ships the public
   key and verifies `index.json.sig` with Node's built-in `crypto.verify` (no new dependency);
   an index that fails is ignored with a visible error. A key rotation ships in an app release.
   This is independent of SignPath: SignPath signs Windows programs (Authenticode), not data.
2. **Every package download is pinned** by the SHA-256 and size in the signed index (the same
   rule as `third-party-binaries.json`): download to `<file>.partial` with the update check's
   `IDownloadService`, check size and hash with its `IChecksumService` helpers, then hand the
   file to `Registry.install()`. A mismatch deletes the file. Only HTTPS URLs on an
   allow-list of hosts (`github.com`, `objects.githubusercontent.com`) are fetched.
3. **Packages contain no programs.** `Registry.install()` refuses a zip with `.exe`, `.dll`,
   `.pyd`, `.bat`, `.ps1`, `.cmd`, `.js` and similar, any file over a size limit (e.g. 50 MB for a
   `.civil`, 5 MB otherwise), symlinks, and paths outside the folder (the last one is already
   checked).
4. **Python hooks are never trusted by installing.** The trust store stays keyed by id + code
   hash, the Trust button stays on the Code Packs page, and the card shows "contains code: read
   it before trusting it" with a link to the file. The index's `hooksSha256` lets the page say
   "this is the code the reviewers saw" or "this code differs from the reviewed copy".
5. **Programs (optional components) come only signed**, see §6.

Decided (D3, 2026-10-30): the index is signed from the first release. The owner creates the
Ed25519 key pair in M0 and keeps the private key offline with a backup; only the public key is
committed (in the app and in `saengine-index`). A test key, marked as such, signs the index in CI
and in development builds, and release builds accept only the owner's key.

## 5. In the app: where install, update and remove live

One page, the existing **Code Packs** page (`codePacksEditor.ts`), renamed **Packages** (D8) and
opened from ≡ → Packages… (the old command id stays as an alias):

- **Installed** (today's list): every kind, filter chips *Design codes · Structure templates ·
  Building templates*, scope badge (built-in / user / project), version, "update available",
  Trust state, Remove (user and project scope; built-in cannot be removed, only shadowed).
- **Browse**: the index's packages as cards (preview, name, kind, country, author, licence,
  size, official/community, "contains code"). Install asks *where* only for design codes
  (user or this project, as today); templates go to the user folder.
- **Updates**: installed packages with a newer index version. Updating a project-scope design
  code asks first, because it changes a project's results; the report already records the pack
  version, so a re-run after an update is traceable.
- **Install from File…**: today's action, now for every kind (offline install, §7).

Links, not copies (no duplication):

- Project Settings → Design code: the dropdown lists installed design-code packages and ends
  with *Get more design codes…*, which opens Packages → Browse filtered to design codes.
- New Building wizard: a *Start from template* row lists installed building templates (spec
  templates prefill the form) and *Get more…* opens Packages → Browse filtered.
- Modeller Generate panel: the shape list shows installed structure-template presets grouped by
  package, and *Get more…*.
- Welcome page: *New Project from Template…* (full building templates).

Online behaviour: the index is fetched when the Packages page opens and at most once a day in
the background (beside the update check), never at startup on the critical path, and a
setting turns it off (`saengine.packages.checkOnline`). Offline, the page shows the installed
packages and the last index it saw.

## 6. Modular installer

Today: one Inno Setup per-user setup with everything: the workbench, bundled Python (about 600
MB on disk: IfcOpenShell, gmsh, SciPy, typst, matplotlib), EnergyPlus 26.2.0, LibreCAD 2.2.1.6
and LibreDWG 0.14 (pinned in `scripts/ci/third-party-binaries.json`), and BNBC 2020.

Sizes (on disk unless said; the setup's own size is printed by the build but not recorded in
the docs: M6 records it):

| Part | Size | Source of the figure |
| --- | --- | --- |
| Bundled Python (SAEngine, OpenSeesPy, IfcOpenShell, gmsh, SciPy, typst, matplotlib…) | about 600 MB | `docs/install/README.md` |
| Workbench (Electron + app) | about 400–500 MB (estimate; measure in M6) | — |
| EnergyPlus minimal runtime | about 62 MB | `build-installer.ps1` |
| LibreCAD trimmed (download 84.6 MB) | about 80–100 MB target, 316 MB untrimmed | `third-party-binaries.json`, notes |
| LibreDWG (`dwg2dxf` + DLL; zip 12.1 MB) | a few MB | `third-party-binaries.json` |
| Third-party sources | about 300 MB | separate release asset, not in the setup |

So the optional programs are roughly 150–170 MB of an install of about 1.2 GB: worth making
optional (smaller install, fewer GPL programs on a PC that does not need them), but the core is
dominated by Python. A smaller core later means trimming Python (the Jupyter packages pulled in
by `rich[jupyter]`, matplotlib if only used for a few plots), which is a separate task, not part
of the marketplace.

Inno Setup supports this natively with `[Types]` and `[Components]` (+ `Components:` on
`[Files]` entries), so the setup stays one file and the user ticks what they want:

| Component | Contents | Default | Notes |
| --- | --- | --- | --- |
| **Core** (fixed) | workbench, Python runtime and the SAEngine package, OpenSeesPy, gmsh, IfcOpenShell, BNBC 2020, the built-in `saengine-shapes` package | always | cannot be split further without changing what the Python runtime imports |
| **Energy simulation** | EnergyPlus (HVAC loads, thermal) | on in *Full*, off in *Compact* | the HVAC part shows "EnergyPlus not installed: Add component…" instead of failing |
| **CAD editor** | LibreCAD (GPL-2.0-only, shipped alongside, never linked) + GPL/Qt notices | on in *Full* | drawings are still produced by ezdxf without it; only "Open in LibreCAD" needs it |
| **DWG import/export** | LibreDWG `dwg2dxf`/`dxf2dwg` (GPL-3.0-or-later) | on in *Full* | DXF works without it |
| **Third-party sources** | the copyleft source archives (about 300 MB) | not in the setup | stay a separate release asset (as today); the setup links to it |

Setup types: **Full** (everything), **Compact** (core only), **Custom**.

Components that are *not* recommended as optional (D6): the MEP disciplines, code packs and
Bangla. MEP is Python and TypeScript inside the core (`saengine.mep`, `hvac`, `plumbing`,
`electrical`, `fire`; one statically imported workbench contribution; a hard-coded
`DISCIPLINES` dict in `library/mep.py`); its size is small next to the core and making it
optional would need feature flags in many parts for little gain. BNBC is the default design code
and must stay built-in. Bangla is a VS Code language pack extension
(`saengine-language-pack-bn`) built into the setup, small, so it stays in the core. More
languages, and an office's own terms, come as packages of the kind `languagePack` (below).

**Adding a component later** without reinstalling (round M6): the Packages page gains a
*Components* section that lists the optional components with their state. Two options (D4):

- (a) *Re-run the setup* (recommended first): "Add component…" downloads the SAEngine setup of
  the installed version (from the SAEngine release, SHA-256 pinned in the release's own
  `.sha256`, and Authenticode-checked once SignPath signs it) and runs it with
  `/COMPONENTS="energyplus"` so Inno Setup adds only that part. One code path, one signature.
  Until the setup is signed (D7), the app does not download it: *Add component…* asks for the
  setup file (or opens the release page) and checks its SHA-256 against the release's `.sha256`
  before running it.
- (b) *Component zips*: the release also publishes `SAEngine-<version>-component-<name>.zip`,
  pinned in a release manifest and unpacked into the install folder. Faster, but it downloads
  programs outside a signed setup, so it should wait for signing (D3, D7).

How the app finds a component stays as it is today (the bundled path first, then a user-set
path), plus: a missing component is a *state*, not an error, everywhere it is used.

**Built in M6 (2026-10-30)**, option (a): `code.iss` has `[Types]` Full/Compact/Custom and the
components `energyplus`, `librecad`, `libredwg` (a component left out is removed by
`[InstallDelete]`); the backend's `components/list` and the shared process's `cadProgram`
report each state from the existing finders; *Add Component...* (in the HVAC results,
*Calculate Loads*, *Open in CAD*, DWG underlays) and **Help › Installer Components...** ask for
the setup with its `.sha256`, check it and run it with `/COMPONENTS=`. Until the Packages page
exists the list lives in the Help menu; M3's *Components* section should open that same list
(`saengine.components.show`), not a second one. User docs: `docs/install/README.md`
(Components). Measured component sizes: EnergyPlus 59 MB, LibreCAD 115 MB, LibreDWG
30 MB on disk (204 MB together); a local setup with all three was 711 MB.

**AI assistant component (2026-10-31, owner).** The built-in Copilot extension
(`resources\app\extensions\copilot`, about 280 MB, most of it the Copilot runtime) is the fourth
component, `ai`: in Full, out of Compact. AI that builds and edits structures is planned, so
Copilot stays, but only for those who want it. The MCP server (`docs/ai-assistants.md`) is core
and works without it. The same day **Git** (`git`: Git, GitHub, merge-conflict) and
**Collaboration** (`collaboration`: port forwarding, Microsoft sign-in; live collaboration joins it
when built) became components too; GitHub sign-in is installed with either AI or Git.

### Code modules: one repository now, mirrored one way

Decided by the owner on 2026-10-31. Code that will one day install as its own package (steel
design first; timber when it exists) stays **developed in SAEngine**, and each module also gets
its own repository that is a **read-only mirror**: `scripts/modules/<id>.json` lists the module's
paths and target repository, and `python -I scripts/modules/mirror.py <id> --push` replaces the
repository's content with those paths at the current SAEngine commit (README, LICENSE and
`MIRROR.json` with the commit are generated). Work never happens in the mirror, so there is one
live copy only. Moving a module out for real (its repository becomes the live copy, SAEngine
installs it from the Packages page) needs a stable design-module interface and is far off.
Concrete design and BNBC stay in the core. The code-pack data a module uses (for example
`bnbc2020/data/steel.json`) stays with its code pack (`saengine-design-codes`).

| Module | Repository | Paths |
| --- | --- | --- |
| steel-design | `saengine-steel-design` | `scripts/modules/steel-design.json` (design/steel, the steel design, proposal and connection modules, section library, drawing sheets, verification cases, tests, the FEM steel panel) |

## 7. Offline install

Many offices have slow or metered connections, so offline is first-class:

- **One package**: the `.zip` from the index (or one a colleague made with *Export Package…*)
  installs with *Install from File…*; the registry validates it exactly as an online install.
  A zip that is not in a signed index is installed as "local" and labelled so; its hooks still
  need trust.
- **An offline bundle**: a folder or zip with `index.json`, `index.json.sig` and the package
  zips (built by the `saengine-index` release as `saengine-packages-offline-<date>.zip`).
  *Install from File…* on the bundle shows it as a Browse list; signature and hashes are checked
  the same way.
- **Components offline**: the Full setup is itself the offline installer for components.

## 8. Rounds

Effort is in focused rounds of the size used so far (one round ≈ one integrator day with
parallel agents). The first two can run as side tracks; M3 and M5 touch shared hotspots
(registry, wizard, Generate panel) and belong to core rounds.

| Round | Scope | Effort | Depends on |
| --- | --- | --- | --- |
| **M0 Decide** | this document; the remaining decisions; create the four repositories after the transfer, and the signing key | 0.5 round (owner) | — |
| **M1 Manifest + registry kinds** | `kind`, `requires`, `contents`, `preview` in `PackManifest`; per-kind discovery; `requires` checks; refuse executables in zips; CLI `--kind`; schema export; tests (BNBC results unchanged) | 1 round | M0 |
| **M2 Package repos + index** | the three kind repositories and `saengine-index`: shared CI workflow, validation, `build_index.py`, signed `index.json`, first content: `saengine-shapes` presets, `DEFAULT_FORM` as the first spec template, BNBC 2020 mirrored (read-only copy), one sample regional design code | 1 round (side track) | M1 |
| **M3 Packages page** | rename Code Packs → Packages; Installed/Browse/Updates/Install from File; index fetch + Ed25519 verify + pinned download in the main process; remove; links from Project Settings, the wizard, the Generate panel | 1.5–2 rounds | M1, M2 |
| **M4 Templates applied** | structure presets in the Generate panel; spec templates in the wizard; full templates via *New Project from Template…* on the `.civil` path; inputs-only check | 1–1.5 rounds | M3 |
| **M5 Coded templates** | new shape kinds through trusted hooks (`local(params)` + parameter schema), the form generated from the schema, the same `insert()`; review rules in the packages repo | 1 round | M4 |
| **M6 Modular installer** | `[Types]`/`[Components]` in `code.iss`; component states in the app ("not installed: Add component…"); *Add component* by re-running the setup; sizes printed by the build; walk-through at 1366×768 and 1920×1080 | 1–1.5 rounds | independent of M1–M5; needs D4, D6 |
| **M7 Signing + component zips** | SignPath for the setup and `SAEngine.exe`; Authenticode check before running a downloaded setup; optional component zips | 1 round + SignPath approval wait | repo transfer, SignPath |
| **M8 Offline bundle + docs** | offline bundle build and install; `docs/packages.md` (user) and the packages repo's CONTRIBUTING (authors); manual chapter | 0.5 round | M3 |

Total: about **8–10 rounds**, of which M6 can run in parallel with M1–M4. A first useful
release (browse and install design codes and structure presets from the official index) is M1 +
M2 + M3, about 3.5–4 rounds.

**Built in M2 (2026-10-30)** (pull requests in the four repositories, none merged or released
yet): `saengine-index` holds `sources.json`, the models and JSON Schemas of `sources.json`,
`packages.json` (one release's manifest, `saengine.packageRelease/1`) and `index.json`
(`saengine.packageIndex/1`, as in §3 plus `repository` and `tag`), the reusable workflows
`validate-packages.yml` (SAEngine's `codepack validate --kind` on each changed package, then
`check_packages.py`: SPDX licence, a code licence for hooks, previews ≤ 256 KB and ≤ 1024 px,
a CODEOWNERS entry for packages with hooks, a new version for a changed package, mirrors equal
to their SAEngine commit) and `publish-packages.yml` (on a `packages-*` tag: reproducible
`<id>-<version>.zip` for each version not yet released, `packages.json`, a GitHub Release, a
dispatch to the index; a dry run keeps the files as an artifact), `build_index.py` (verifies
every asset's size and SHA-256) and `sign_index.py` (Ed25519; `index.json.sig` is
`saengine.packageIndexSignature/1` with a key id; a TEST KEY derived from a published seed
signs in CI, the owner's offline key signs releases, also through `openssl pkeyutl`). The three
kind repositories call those workflows and hold the first content: BNBC 2020 and
`saengine-shapes` as mirrors (`mirrors.json`, written by `scripts/marketplace/mirror_packages.py`),
`saengine-default-building` (the wizard's `DEFAULT_FORM` as a `BuildingSpec`; the wizard still
has its own copy until M4 reads the template) and a synthetic sample design code that extends
`bnbc2020`. In SAEngine: the built-in `saengine-shapes` package and the inputs-only check of
`template.civil` (`project.archive.inputs_only_problems`). The location-precision and
drawing-author checks of full templates are left for M4.

**Built in M3 (2026-11-01)**, track T38: the Code Packs page is now **Packages** (≡ › Packages...,
`saengine.packages.show`; `saengine.codePacks.show` stays as an alias) with the tabs *Installed*,
*Browse* and *Updates*, a kind filter (*All · Design codes · Structure templates · Building
templates*), *Install from File...* for every kind, *Remove...* (user and project packages; a
package another one extends or requires is refused; its trust entry is dropped) and *Installer
Components...*, which opens the M6 list (`saengine.components.show`). The index
(`saengine.packages.indexUrl`, default the latest release of `saengine-index`) and its
`index.json.sig` are fetched and verified with Ed25519 in the **main process**
(`platform/saengine/electron-main/packagesMainService.ts`, Node `crypto.verify`); the zip is
downloaded there to a private temporary folder, checked against the index's size and SHA-256
(HTTPS on GitHub hosts only), handed to `codes/install` (with `replace` for an update) and
deleted. Release builds accept only the owner's key (`OWNER_INDEX_KEYS` in
`saengineLibrary/common/packageIndex.ts`, **empty until the owner adds the public key**); development
builds also accept the TEST key. The last verified index is kept for offline use; a background
check runs at most once a day in a packaged build and says when installed packages have updates;
`saengine.packages.checkOnline` turns both off. Links: Project Settings' design code list ends with
*Get More Design Codes...*, *Manage Packages...* and *Install from File...*; the New Building
wizard has *Get more building templates...*; the modeller's Generate panel has *Get more structure
templates...*. Backend: `codes/list {kind: "all"}`, `codes/remove`, `codes/install {replace}`,
`Registry.uninstall`, and `saengine codepack install|remove`. The store sites: each repository gets a
static catalogue on an orphan `gh-pages` branch, built by `scripts/marketplace/store-site/`
(`build_store.py`, `store-pages.yml`); the owner copies them into the four repositories and enables
Pages (see that folder's README).

**Built in M4 (2026-11-01)**, track T39: templates are applied where they are used, and installed
only on the Packages page. The backend's `codes/templates` (`saengine.codes.catalogue`) lists the
presets of the structure templates in force and the building templates (specifications and full
templates), leaving out a file that does not validate. The modeller's **Generate panel** has a
*Start from a structure template...* picker grouped by package (the built-in `saengine-shapes`
first); a preset fills the form, keeps where the shape is placed and goes through the same
`shape_geometry` and `insert`. The **New Building wizard** has a *Start from* row: a
specification prefills the form (`formFromSpec`), a full template opens *New Project from
Template...*; the wizard's own `DEFAULT_FORM` is gone: it starts from the built-in building
template **`saengine-default-building`** (now in `codes/packs/`; the package repository should
mirror it from here). **New Project from Template...** (File menu, ≡ menu, start page) picks an
installed full template, checks it again with `codes/checkTemplate` and opens it through the
`.civil` import as a new project. The checks of a full template
(`project.archive.template_problems`, also run by `codepack validate`): inputs only (M2), no
latitude or longitude with more than two decimals (finer than a town) and no plot outline, and no
person named on drawings or project files (drawn by, checked by, client...) other than the
package's author.

**Built in M5, M7 and M8 (2026-11-01)**, track T40.
*M5 coded templates*: a structure template file that names a `generator` (`CodedTemplate` in
`codes/contents.py`: `generator`, `parameters` as a small JSON Schema, `values`) is made by that
function of the package's `hooks.py`, through `codes/codedGeometry` (`saengine.codes.coded`): only
when the package is trusted (the same trust store; `codes/trust` now takes `kind`), parameters
checked first, the result placed and inserted like a built-in shape. The Generate panel builds the
form from the schema; the Packages page offers *Trust This Package's Code...* for templates.
Review rules for code are in `scripts/marketplace/CONTRIBUTING-packages.md`.
*M7 signing*: `platform/saengine/node/authenticode.ts` checks a setup with Windows'
`Get-AuthenticodeSignature`; *Add Component...* requires a valid signature by product.json's
`saengineSigning.publisher` once the owner sets it (until then the SHA-256 only, as before).
`scripts/installer/component_zips.py` builds the component zips and their manifest; by D7 the app
offers them only after signing. The SignPath steps for `release.yml` and the owner's sign-up
steps are in `scripts/signing/` (**waiting for the owner**).
*M8 offline bundle and docs*: `scripts/marketplace/build_offline_bundle.py` builds
`saengine-packages-offline-<date>.zip`; *Install from File...* on a bundle (zip or folder) verifies
its index in the main process and lists it in Browse, installing from its zips with the same
checks. User docs: `docs/packages.md` and the manual chapter `docs/manual/14-packages.md`; authors:
`scripts/marketplace/CONTRIBUTING-packages.md` (to be copied into the package repositories).

Every round ends with the usability walk-through (fresh project, both window sizes) and a
duplication check: no second installer UI, no second manifest, no second trust store.

## 9. Decisions

Settled by the owner on 2026-10-30:

| # | Decision | Answer |
| --- | --- | --- |
| D2 | One repository or one per kind | **one per kind** (design codes, structure templates, building templates) plus `saengine-index` |
| D3 | Sign the index before SignPath | **yes**: Ed25519, the owner's key, from the first release |
| D6 | Optional installer components | **EnergyPlus, LibreCAD, LibreDWG**, and (2026-10-31) the **AI assistant** (Copilot), **Git** and **Collaboration** (port forwarding, Microsoft sign-in; live collaboration later); MEP, BNBC and Bangla stay in the core |
| D10 | Community packages in the first release | **no**: official packages first; community entries after M5 with review rules |

Still open (the plan follows the recommendation until told otherwise):

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | The organisation's exact GitHub login and the repository names | `saengine-design-codes`, `saengine-structure-templates`, `saengine-building-templates`, `saengine-index`, created after the SAEngine transfer |
| D4 | How a component is added after install | re-run the setup with `/COMPONENTS=`; component zips only after signing |
| D5 | Do the six built-in shapes' presets become a package (built-in and published) | yes, `saengine-shapes`; the shape classes stay in core |
| D7 | May the app download any program before SignPath signing exists | no; until then programs come only inside a setup the user runs |
| D8 | Name of the page | "Packages" (alternatives: "Marketplace", "Add-ons") |
| D9 | Keep `saengine.codePack/1` and the `code-packs` folders, or rename to `saengine.package/1` with a migration | keep; add `kind` |
| D11 | Default licence of packages | CC-BY-4.0 for data and templates, AGPL-3.0 for hooks (code that runs inside SAEngine) |
