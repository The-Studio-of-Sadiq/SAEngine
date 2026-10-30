# Design code packs

SAEngine designs to **BNBC 2020** (the Bangladesh National Building Code) out of the box. A
*code pack* is how you make it design to the code of your own country or region instead: the
code's tables and factors (towns and their hazard, live loads, load combinations, seismic and
wind coefficients, φ factors, cover, bar sizes, detailing limits) live in a folder of plain
JSON files that you can copy, change, check and share, without changing SAEngine itself.

You do not need to be a programmer to write a pack. Most packs start from BNBC 2020 and change
only what differs in their region: a few towns, a wind speed, a combination factor.

- [What a pack is](#what-a-pack-is)
- [Start a pack](#start-a-pack)
- [The tables](#the-tables)
- [Inheritance: change only what differs](#inheritance-change-only-what-differs)
- [Data or formula? Hooks and trust](#data-or-formula-hooks-and-trust)
- [Check a pack](#check-a-pack)
- [Use and share a pack](#use-and-share-a-pack)
- [The pack in the report](#the-pack-in-the-report)
- [Limits of this version](#limits-of-this-version)
- [Command reference](#command-reference)

## What a pack is

A pack is a folder:

```text
bd-coastal/
  pack.json            what the pack is: id, name, edition, which pack it extends, sources
  data/
    locations.json     one file per table the pack provides
    combinations.json
    ...
  docs/                your notes, the extracts of the code you may share, calculations
  README.md
```

`pack.json`, for a pack that starts from BNBC 2020:

```json
{
  "schema": "saengine.codePack/1",
  "id": "bd-coastal",
  "name": "Bangladesh coastal belt",
  "edition": "BNBC 2020 with the local schedule",
  "country": "BD",
  "region": "Coastal districts",
  "version": "1.0.0",
  "extends": "bnbc2020",
  "covers": ["locations", "combinations"],
  "description": "BNBC 2020 with the local towns and the 0.5L seismic combination.",
  "sources": [{ "id": "LOCAL", "title": "Local schedule", "edition": "2026" }],
  "clauses": { "locations": ["Local schedule, Table 1"] },
  "author": "A. Engineer, Firm Ltd",
  "licence": "CC-BY-4.0",
  "hooks": null
}
```

| Key | What it is |
| --- | --- |
| `id` | Short id: lower-case letters, digits, `.`, `_`, `-`. Projects refer to the pack by it, so keep it once the pack is in use. |
| `name`, `edition` | Shown in Project Settings and in the report. |
| `country`, `region` | ISO country code (`BD`, `NP`, `LK`, ...) and, for a local pack, the region. |
| `version` | The version of *your pack*; raise it whenever you change a value. |
| `extends` | The pack this one starts from (`bnbc2020`); `null` for a pack that provides every table itself. |
| `covers` | The tables this pack provides. |
| `sources`, `clauses` | Where the values come from: the documents, and the clauses by table. |
| `author`, `licence` | Who prepared it and on what terms it may be shared. |
| `hooks` | Optional Python file for formulas ([below](#data-or-formula-hooks-and-trust)); `null` for a data-only pack. |
| `requires` | Optional: what the pack needs, `{"saengine": ">=0.0.47", "packages": {"bnbc2020": ">=1.0.0"}}`. A pack that needs a newer SAEngine is not installed; a missing or too old required package is reported and the pack is not used until it is installed. |
| `kind`, `contents`, `preview` | Optional. `kind` is `designCode` (the default: leave it out); the other kinds are templates ([Other package kinds](#other-package-kinds)). `contents` lists the pack's files (default `data/*.json`); `preview` is a small card image in the folder. |

JSON has no comments. In the data files, keys that start with `$` are not data: `$help` and
`$example` are notes for you, and a few others are instructions to the loader (`$replace`,
`$remove`, `$sources`, below). `pack.json` takes only the keys above.

## Start a pack

In the app: **≡ → Code Packs… → New Code Pack…**, give the id, the name and the pack to start
from (BNBC 2020). SAEngine creates the folder and opens `pack.json`.

From a terminal (see [the command line](cli.md)):

```console
> saengine codepack new bd-coastal --name "Bangladesh coastal belt" --extends bnbc2020 --dest .
created bd-coastal
  edit bd-coastal\pack.json and the tables you change in bd-coastal\data
  then: saengine codepack validate "bd-coastal"
```

The new pack has one file in `data/` for every table of its parent. Each file holds only help:
what the table is, and under `$example` the first entries of the parent's table, so you can see
the format. As created, the pack changes nothing: it designs exactly as BNBC 2020. Then, for
each table you change:

1. write your entries next to `$help` (in the parent's format, as `$example` shows);
2. add the table's name to `covers` in `pack.json`;
3. say where the values come from: `"$sources": ["Local schedule, Table 1"]` in the file, or
   the table under `clauses` in `pack.json`.

Leave the other files as they are (or delete them): a table you do not provide comes from the
parent unchanged.

## The tables

Every table is checked against a model (the JSON Schema of each table is generated from the
same model SAEngine reads). The examples are from the BNBC 2020 pack
(`python/src/saengine/codes/packs/bnbc2020/data/`), which names the clause and page of each
table in its own `source`.

| Table | What it holds |
| --- | --- |
| `locations` | Towns with their seismic zone and basic wind speed. |
| `zoneCoefficients` | Seismic zone coefficient Z by zone. |
| `occupancyCategories` | Occupancy (risk) categories with their seismic and wind importance factors. |
| `areaLoads` | Minimum live loads by use of the floor area [kN/m²]. |
| `combinations` | Load cases (`loadCases`), the strength, temperature and gravity combinations (lists matched by `name`), the dead load factors of the seismic combinations (`seismicDeadUpper`, `seismicDeadLower`) and the overstrength (Ω0) note (`overstrength`). The BNBC pack has no service combinations. |
| `seismic` | Site classes, structural systems (R, Ω0, Cd, height limits), period coefficients, the seismic design category table, drift limits, the other numbers of the seismic analysis. |
| `wind` | Exposure categories and profiles, directionality, topographic and gust factors, pressure coefficients. |
| `materials` | Material constants and limits (εcu, Es, the grades permitted in seismic members, ...). |
| `factors` | Strength reduction factors φ of reinforced concrete. |
| `concrete` | Bar sizes, cover, minimum thickness tables, steel ratio limits, spacing, stiffness modifiers. |
| `detailing` | Detailing limits that are plain numbers: special moment frames, joints, walls, lintels. |
| `steel` | φ factors and slenderness limits of structural steel. |
| `foundations` | Pile safety factors, partial factors of skin and base resistance, strut-and-tie factors. |

`saengine codepack show bnbc2020` lists them with their clauses. Short examples:

**locations**: towns keyed by a short id; `zone` points into `zoneCoefficients`.

```json
{ "locations": { "dhaka": { "name": "Dhaka", "zone": 2, "windSpeed": 65.7 } } }
```

**zoneCoefficients**: Z by zone.

```json
{ "zones": { "1": 0.12, "2": 0.2, "3": 0.28, "4": 0.36 } }
```

**areaLoads**: live loads by use.

```json
{ "uses": { "office": { "name": "Office", "live": 2.4 } } }
```

**combinations**: a list of named combinations per category, each with its load factors (`D`
includes the superimposed dead load; `W` and `E` are expanded to both plan directions and
signs by SAEngine).

```json
{
  "strength": [
    { "name": "1.2D + 1.6L + 0.5Lr", "factors": { "D": 1.2, "L": 1.6, "Lr": 0.5 } }
  ],
  "seismicDeadUpper": 1.2,
  "seismicDeadLower": 0.9
}
```

**seismic**: for instance a structural system and a site class.

```json
{
  "systems": {
    "rcSmf": { "name": "RC special moment frame", "R": 8.0, "Omega0": 3.0, "Cd": 5.5,
               "heightLimits": { "B": null, "C": null, "D": null } }
  },
  "siteClasses": { "SC": { "description": "Dense sand, stiff clay", "S": 1.15,
                           "TB": 0.2, "TC": 0.6, "TD": 2.0 } }
}
```

**wind**: exposures and factors.

```json
{ "exposures": { "B": { "description": "Open terrain", "alpha": 9.5, "zg": 274.32 } },
  "directionality": 0.85, "gust": 0.85 }
```

**factors**: φ.

```json
{ "phi": { "tension": 0.9, "compressionTied": 0.65, "compressionSpiral": 0.75, "shear": 0.75 } }
```

**concrete**, **detailing**, **materials**, **steel**, **foundations**: groups of named
numbers, for instance `{"cover": {"lintel": 25.0}}`,
`{"special": {"beamRhoMax": 0.025}}`, `{"steelE": 200000.0}`,
`{"phi": {"compression": 0.9}}`, `{"sptSafety": 3.5}`. The help in each file of a new pack
shows the full list of keys of its table.

Every table also accepts `source` (the clause the table comes from, as text) and `sources`
(clauses of single entries: `{"shearSeismic": "Sec 6.2.3.3(a)"}`).

After inheritance every key the program reads must be present and in range (φ: 0 < φ ≤ 1;
ratios: 0 < x < 1). Unknown keys are refused, so a misspelt key is an error rather than ignored;
the exceptions are extra φ factors and extra bar sets, which hooks may use. The required keys of
each table are in its JSON Schema (`python/src/saengine/codes/schemas/<table>.schema.json`).

## Inheritance: change only what differs

A pack that `extends` another starts from all of its tables. In a table you provide, only what
you write changes:

- **Objects are merged key by key.** To change Chattogram's wind speed and add a town:

  ```json
  {
    "locations": {
      "chattogram": { "windSpeed": 82.0 },
      "northford": { "name": "Northford", "zone": 3, "windSpeed": 58.0 }
    }
  }
  ```

  Chattogram keeps its zone; every other town stays as in BNBC 2020.

- **Lists of named items** (the combinations) are matched by `name`: an item with a name the
  parent has changes that item, a new name is added at the end, and `"$remove": true` drops
  the parent's item:

  ```json
  {
    "strength": [
      { "name": "1.2D + 1.0E + 1.0L", "$remove": true },
      { "name": "1.2D + 1.0E + 0.5L", "factors": { "D": 1.2, "E": 1.0, "L": 0.5 } }
    ]
  }
  ```

  Other lists (bar sizes, for instance) are replaced whole by yours.

- **Drop keys**: `"$remove": ["rangpur", "sylhet"]` in an object drops those entries of the
  parent.

- **Replace a whole table**: `"$replace": true` at the top of the file (or in any object) uses
  yours instead of the parent's, without merging: for a region whose list of towns has nothing
  in common with the parent's, say.

A pack can extend a pack that extends another (`city` → `region` → `bnbc2020`). A pack in a
project may also extend its own id (`"id": "bnbc2020", "extends": "bnbc2020"`): it then patches
the built-in BNBC pack for that project only.

The example pack `python/tests/data/codepacks/example-region/` does all of this on invented
values: two towns, one wind speed, one combination. Compare it with BNBC 2020:

```console
> saengine codepack diff bnbc2020 python/tests/data/codepacks/example-region
- combinations.strength.[1.2D + 1.0E + 1.0L]: {"name": "1.2D + 1.0E + 1.0L", "factors": {...
+ combinations.strength.[1.2D + 1.0E + 0.5L]: {"name": "1.2D + 1.0E + 0.5L", "factors": {...
~ locations.source: "BNBC 2020 Part 6 Table 6.2.8 (p. 600) basic wind speeds; ..." -> "..."
~ locations.locations.chattogram.windSpeed: 80.0 -> 82.0
+ locations.locations.northford: {"name": "Northford", "zone": 3, "windSpeed": 58.0}
+ locations.locations.saltmarsh: {"name": "Saltmarsh", "zone": 1, "windSpeed": 84.5}
6 differences
```

This is the review to do before a regional pack is used: every line is a value that differs
from BNBC 2020, and nothing else does.

## Data or formula? Hooks and trust

A pack changes **numbers**. The **formulas** stay in SAEngine: the flexure and shear strength
of a section, the equivalent static base shear and its distribution, the wind pressure profile,
development lengths, punching shear, and so on. Most codes derived from ACI 318 and ASCE 7 (as
BNBC 2020 is) use the same formulas with different numbers, and a data pack is enough.

| A pack can change (data) | Needs a hook (formula) |
| --- | --- |
| towns, zones, Z, wind speeds | a different spectrum shape or base shear formula |
| live loads, importance factors | a different wind pressure method |
| load combinations and their factors | a different section strength model (another stress block, another shear formula) |
| site classes and their factors, R, Ω0, Cd, height limits, period coefficients, drift limits | a different development length or lap formula |
| φ factors, cover, bar sizes, minimum thicknesses, steel ratio limits | a different slenderness method |
| detailing limits that are plain numbers | rules that are conditions rather than numbers |
| pile safety factors, partial factors | a different bearing capacity method |

When a formula differs, a pack can name a Python file in `hooks` (`"hooks": "hooks.py"`), whose
functions replace SAEngine's functions of the same name. A hook is a program: it can do
anything a program on your computer can. So SAEngine **never runs a hook until you trust the
pack** (Code Packs page → the pack → *Trust*), the trust is recorded for exactly that code, and
**any edit of the pack's Python files withdraws the trust** until you trust it again. Built-in
packs are trusted. Trust a pack's hooks only when you know who wrote them and have read them;
a data-only pack needs no trust at all.

## Check a pack

```console
> saengine codepack validate bd-coastal
warning: pack.json: no sources or clauses: say where the values come from
bd-coastal: ok (0 errors, 1 warning)
```

`validate` reads the pack the way a project does: `pack.json`, every data file, the parent
packs, then every resolved table against its model (a negative wind speed, a missing factor, a
misspelt key are errors). It also warns about a file with values whose table is not in
`covers`, a table in `covers` whose file has only help, and a pack without sources. It exits
with code 1 when the pack has an error, so it can run in continuous integration. In the app:
Code Packs page → the pack → **Validate**.

`saengine codepack show <id or folder>` lists a pack's tables, which are its own and which are
inherited, the clauses of each, its trust state and its problems.

A pack holds data, and Python `hooks` at most: a pack with a program or script (`.exe`,
`.dll`, `.pyd`, `.bat`, `.cmd`, `.ps1`, `.js`, ...), a link, a file over 5 MB (50 MB for a
`.civil`) or over 200 MB in all is refused when installed and reported as an error when found.

## Use and share a pack

Where SAEngine finds packs (the same id in a higher place wins):

1. **the project**: `02 Project Settings/code-packs/<id>/`: the pack travels with the project,
   its versions and its `.civil` archive;
2. **your user folder**: `%APPDATA%\SAEngine\code-packs\<id>\` on Windows
   (`~/Library/Application Support/SAEngine/code-packs` on macOS, `~/.config/SAEngine/code-packs`
   elsewhere): available to every project on this computer;
3. **built-in**: `bnbc2020`, shipped with SAEngine.

To use a pack, choose it in **02 Project Settings → Design code**. A project without a choice
(every project made before code packs) uses `bnbc2020`, and designs exactly as before.

To share a pack, zip its folder and send it; the receiver installs it with **≡ → Code Packs… →
Install Code Pack…** (the zip or the folder, into the user folder or into the project), or
copies the folder into one of the places above. A project that uses a pack of its own carries it
along: send the project or its `.civil` archive and the pack goes with it.

## The pack in the report

The design report states the code pack the project was designed to on its cover ("Code
pack"): its name, id, edition and version. A pack that extends another reads "BNBC 2020
(bnbc2020), modified by: <name> (<id>), <edition>, pack version <v>". A user or project copy that
replaces a built-in pack of the same id is named with its place ("modified from the built-in
code"), and the pack's warnings are listed among the report's warnings. Keep `version` up to
date when you change a value, so that a report always says which values it used.

## Limits of this version

**What follows the project's pack today.** The project's choice (`codePack`) is read by:

- the site and hazard values of Project Settings (town, zone, Z, basic wind speed, importance
  factors, R, Ω0, Cd: `locations`, `zoneCoefficients`, `occupancyCategories`,
  `seismic.systems`), the live load minimums the settings are checked against (`areaLoads`) and
  the report's design basis;
- the loads of the analysis model: the equivalent static earthquake (spectrum: `seismic.
  siteClasses`, `dampingEta`; period: `seismic.periodCoefficients`), the seismic weight's share
  of live load (`seismic.liveShare`) and the wind pressures (`wind`: exposure profiles, Kd, Kzt,
  G, Cp);
- the response spectrum design: zone from Z, Seismic Design Category (`seismic.
  designCategories`), drift limits (`seismic.allowableDrift`), a_h (`seismic.pgaFactor`);
- the load combinations made from a pack (`combinations`), through
  `saengine.library.settings.strength_combinations(pack=...)`. A project keeps its combinations
  in its settings, and choosing a pack does not rewrite them; in the app, new projects and
  **Reset Combinations to BNBC 2020** still use BNBC 2020's: enter a pack's combinations in
  Project Settings → Load combinations.
- the seismic detailing scope of the design (which provisions of the code's earthquake chapter
  apply): the system's row of the systems table (R, Ω0, Cd, height limits per Seismic Design
  Category, frame detailing level, special walls: `seismic.systems`), the detailing level each
  category requires (`seismic.requiredDetailing`) and the material limits of special frames and
  walls (`materials`: `seismicFcMin`, `lightweightFcMax`, `lightweightDensity`,
  `seismicRebarFy`, `seismicRebarFyMax`, `gradeTolerance`, `fyActualMargin`, `fyRetestMargin`,
  `fuFyMin`);
- the building generator's choice of the seismic force-resisting system (`seismic.systems`,
  `seismic.requiredDetailing`) and its period estimate (`seismic.periodUpperFactor`);
- the steel member design's φ factors and slenderness limits (`steel.phi`: `tensionYield`,
  `tensionRupture`, `compression`, `flexure`, `shear`; `steel.slenderness`).

**What does not follow it yet** (read from the built-in BNBC 2020 values, whatever the pack):
the concrete member design's φ factors, cover, bar sizes, minimum thicknesses and steel ratios,
the seismic detailing limits of the members and joints, the steel connection factors
(`steel.phi`: `bolt`, `bearing`, `blockShear`, `weld`, `plateFlexure`; `steel.netAreaMax`), the
material constants (`materials`: `concreteStrain`, `steelE`, `steelShearModulus`), the lintels
(`detailing.lintels`) and the foundation factors of 9 Substructure and the bill of quantities
(`foundations`, `factors.phi.strutAndTie`): the rest of the `factors`, `concrete`, `detailing`,
`steel`, `foundations` and `materials` tables; the building generator's member sizes; the soil
part (liquefaction's site factors); the settings editor's derived-value hints and its Code
Values panel. A pack's values in those tables are validated and shown, but not used: keep
them equal to BNBC 2020 until a later version wires them. No design function consults hooks
yet.

The project's Location must be one of BNBC 2020's towns (or "Custom" with Z and V): a pack's own
towns are validated and listed but cannot yet be chosen in the settings.

- Packs hold the code's **reference data and plain-number factors**. Design formulas are
  SAEngine's (ACI 318 / BNBC 2020 based); a pack changes them only through trusted hooks.
- The tables cover what SAEngine reads today. A code clause SAEngine does not implement cannot be
  added by a pack's data alone.
- The units are fixed: SI (kN, m, mm, MPa, m/s).
- Wind speeds are part of `locations`; a separate `windSpeeds` table is reserved for codes that
  map wind apart from the towns.
- The names of the load cases (`D`, `L`, `Lr`, `W`, `E`, `F`, `T`) are SAEngine's; a pack changes
  their factors and the combinations, not the set of load cases the program builds.
- The BNBC 2020 pack is transcribed from the values SAEngine used before code packs; the clause
  and page of each table are in its `source`. Check every value of a pack you write against the
  edition of the code that governs your project.

## Other package kinds

The same `pack.json` and the same registry hold the other packages of the marketplace
([marketplace-plan.md](marketplace-plan.md)); `kind` says which:

| Kind | Holds | Checked against | User folder |
| --- | --- | --- | --- |
| `designCode` (default) | `data/<table>.json` | the table models | `%APPDATA%\SAEngine\code-packs\` |
| `structureTemplate` | `templates/*.json`: presets of a built-in shape (`{"name": "Warren truss 24 m", "shape": {"kind": "planeTruss", ...}}`) | the Generate panel's shape model (`structure-template.schema.json`) | `%APPDATA%\SAEngine\packages\structure-templates\` |
| `buildingTemplate` | `spec.json` (a New Building specification) or `template.civil` (an inputs-only project) | the generator's `BuildingSpec` (`building-template.schema.json`), the archive check | `%APPDATA%\SAEngine\packages\building-templates\` |

Templates are installed for the user only (applying one copies it into the project), take no
`extends`, and share the built-in folder and the trust of hooks with design codes. Ids are one
namespace across kinds. Applying templates (the Generate panel, the New Building wizard) comes in
a later round; for now they are listed, validated and installed:
`saengine codepack list --kind all`, `saengine codepack validate <folder> --kind structureTemplate`.

## Command reference

| Command | What it does |
| --- | --- |
| `saengine codepack list [--kind KIND\|all] [--root PROJECT]` | The installed packs: built-in, user, and the project's with `--root`; design codes unless `--kind` says otherwise. |
| `saengine codepack show <id or folder> [--kind KIND] [--root PROJECT]` | A pack's details: inheritance, tables (own or inherited) with their clauses, requires, contents, hooks and trust, problems. |
| `saengine codepack new <id> --dest <dir> [--name N] [--extends bnbc2020] [--edition E] [--country C] [--author A]` | Creates `<dir>/<id>/`, a pack that extends `--extends` (`--extends ""` for none). |
| `saengine codepack validate <folder> [--kind KIND] [--root PROJECT]` | Checks a pack; exit code 1 when it has errors, or with `--kind` when it is of another kind. |
| `saengine codepack diff <a> <b> [--root PROJECT]` | The differences of two packs (ids or folders), table by table and key by key: `+` only in b, `-` only in a, `~` changed. |

`saengine package ...` is the same command. Every command takes `--json` (one JSON document on stdout, as the other `saengine` commands)
and `-q`. Exit codes: 0 ok, 1 the pack has errors (`validate`), 2 usage (unknown pack, bad id,
existing folder), 3 error.
