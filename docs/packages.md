# Packages

A package is a folder with a `pack.json`, installed from SAEngine's Packages page (≡ ›
Packages...), from a `.zip`, or with the command line. How to use them in the app is in the user
manual, [Packages: design codes and templates](manual/14-packages.md); how design code tables are
written is in [code-packs.md](code-packs.md); the plan and the decisions behind the marketplace are
in [marketplace-plan.md](marketplace-plan.md); programming SAEngine (Python API, JSON-RPC, hooks)
in [sdk/README.md](sdk/README.md). Authors of packages: see
`scripts/marketplace/CONTRIBUTING-packages.md`, the CONTRIBUTING of the package repositories.

## Kinds and files

| `kind` in pack.json | Files (`contents`) | Applied by |
| --- | --- | --- |
| `designCode` (the default) | `data/<table>.json`, optional `hooks.py` | Project Settings › Design code |
| `structureTemplate` | `templates/*.json`: presets of a built-in shape, or coded templates; optional `hooks.py` | the Generate panel |
| `buildingTemplate` | `spec.json` (a building specification) or `template.civil` (a whole project, inputs only) | the New Building wizard; New Project from Template... |

Every package may have `requires` (`{"saengine": ">=0.0.50", "packages": {"bnbc2020": ">=1.0.0"}}`),
a `preview` image (PNG, JPEG or WebP, at most 256 KB) and must have a `licence` (SPDX). The JSON
Schemas are in `python/src/saengine/codes/schemas/` (`code-pack.schema.json`,
`structure-template.schema.json`, `building-template.schema.json`).

### Preset of a built-in shape

```json
{ "name": "Warren truss 30 m", "description": "...",
  "shape": { "kind": "planeTruss", "span": 30000, "depth": 3000, "panels": 10,
             "pattern": "warren", "memberType": "MEMBER" } }
```

### Coded template (a new shape kind)

```json
{ "name": "Portal frame", "generator": "portal",
  "parameters": { "type": "object", "required": ["span", "height"],
                  "properties": { "span": { "type": "number", "minimum": 1000, "title": "Span [mm]" },
                                  "height": { "type": "number", "minimum": 1000 } } },
  "values": { "span": 12000, "height": 6000 } }
```

`generator` names a function of the package's `hooks.py`: `portal(params) -> geometry`, where the
geometry is a `saengine.library.shapes.Geometry` or its JSON: `members` (`start`, `end` as
`[x, y, z]` in mm, `type`: a member object type id, or `MEMBER` for the default), `areas`
(`outline`, `type`), `supports` (`at`, `fixity`: `pinned` or `fixed`) and `notes`. The parameters
are numbers, integers, strings or booleans with `minimum`, `maximum`, `enum`, `title`,
`description` and `default`; SAEngine checks them before calling the function, and the Generate
panel builds its form from them. `origin` (`{x, y, z}`) and `rotation` (degrees in plan) place the
result; the geometry then enters the model through the same insertion as a built-in shape.

### Full building template

`template.civil` is a project archive with inputs only. `saengine codepack validate` and New
Project from Template... refuse one that holds results, a soil report, exported deliverables or
the version history, places the site more precisely than a town (latitude or longitude with more
than two decimals, a plot outline), or names anyone on drawings or project files (drawn by,
checked by, client...) other than the package's `author`.

## Safety

- **The package list is signed** (Ed25519). SAEngine verifies `index.json.sig` in the main process
  before it lists anything; release builds accept only the owner's key, development builds also
  the published TEST key.
- **Every download is pinned**: HTTPS from GitHub only, and the zip's size and SHA-256 must match
  the signed list, or it is deleted unused.
- **No programs**: a package holding `.exe`, `.dll`, `.pyd`, scripts (`.bat`, `.ps1`, `.cmd`,
  `.js`...), links, paths outside its folder or oversized files is refused.
- **Code runs only when trusted**: hooks and coded templates never run because a package was
  installed. Trust is per package id and the SHA-256 of all its `.py` files; any change withdraws
  it. Removing a package forgets its trust.
- **Programs of the setup** (optional components) come only inside the SAEngine setup, checked
  against the release's SHA-256 and, once SAEngine is signed, its Authenticode signature
  (`scripts/signing/README.md`).

## Offline bundle

`saengine-packages-offline-<date>.zip` holds `index.json`, `index.json.sig` and `packages/*.zip`.
Install from File... on it lists its packages in Browse; installing copies a zip from the bundle
with the same checks. It is built by `scripts/marketplace/build_offline_bundle.py`.

## Command line

```console
saengine codepack list --kind all              # every package installed
saengine codepack validate <folder> --kind structureTemplate
saengine codepack install <folder|zip> [--scope user|project --root <project>] [--replace]
saengine codepack remove <id> [--kind KIND] [--scope user|project --root <project>]
saengine package ...                           # the same command
```

`validate` exits with 1 when the package has errors, so the package repositories' CI runs it on
every pull request.
