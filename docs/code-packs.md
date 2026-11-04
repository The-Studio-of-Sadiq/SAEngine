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
- [How to override a code value](#how-to-override-a-code-value)
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
  "basis": { "general": "BNBC 2020 with the local schedule" },
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
| `basis` | What the report and the design method say the design follows: `general` (loads and general), `concrete`, `steel` and `method`. Each label a pack leaves out comes from the pack it extends (BNBC 2020: "BNBC 2020", "BNBC 2020 Part 6 Chapter 6", "BNBC 2020 Part 6 Chapter 10", "Strength design (LRFD)"); without any, the pack's `edition`. |
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
| `slabCoefficients` | The two-way slab moment coefficients (BNBC Tables 6.6.8-6.6.11), their limits and the one-way coefficients. |
| `plumbing` | Water supply, drainage and rainwater (BNBC Part 8 Chapters 5-7): water demand by occupancy, storage, fixture units and the probable demand curve, velocity and pressure limits, stacks, drains and vents, septic tank and soak pit, leaders, gutters and storm drains; the pipe diameters, Hazen-Williams C, sleeves and wet-room fixtures SAEngine assumes where the code is silent. |
| `hvac` | Air-conditioning and energy (Part 8 Chapter 2, Part 3 Chapter 4): outside design conditions of the stations, inside conditions, ventilation rates and occupancy, lighting power density, glazing and overhangs; equipment loads, metabolic heat and supply air SAEngine assumes (listed in the report). |
| `electrical` | Electrical services (Part 8 Chapter 1, Sec 4.2.1): load densities, substation, transformer and generator rooms, shafts and risers, earthing, the lightning risk indices and protection; typical equipment sizes and masses for the first layout. |
| `fire` | Fire protection (Part 4): hazard classes and flows, durations, standpipe and hose pressures, pump ratings, sprinkler pipe schedules and spacing; the NFPA values the code leaves out (marked "from memory, to be checked"). |
| `steelSections` | The standard steel shapes: the nominal dimensions of each family (IPE, HEA, HEB: EN 10365; ISMB, ISMC: IS 808; equal angles: EN 10056 / IS 808; SHS, RHS, CHS: EN 10219), the walls rolled per size, the density. SAEngine computes the properties (A, I, S, Z, J, Cw) from them. |

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
3. **built-in**: `bnbc2020`, shipped with SAEngine; `eurocodes` (below); `aci318-asce7-22`, the ASCE 7-22 loads
   (its materials still fall back to `bnbc2020`; the site's SDS, SD1, S1, TL and V are entered
   from the ASCE Hazard Tool; values to check in its `VERIFY.md`); and `is-codes`, the Indian
   Standards loads (below).

To use a pack, choose it in **02 Project Settings → Design code**, or in **New Project →
Design code**, which lists the packs installed on this computer. A project without a choice
(every project made before code packs) uses `bnbc2020`, and designs exactly as before.

The design code is the code pack alone. Project settings written before code packs also have a
`codes` section (the concrete and steel codes as labels, for instance "ACI 318-19"); it is no
longer read, the settings form no longer shows it, and it is dropped the next time the settings
are saved. The report's "Design basis" now states the pack's `basis`.

To share a pack, zip its folder and send it; the receiver installs it with **≡ → Code Packs… →
Install Code Pack…** (the zip or the folder, into the user folder or into the project), or
copies the folder into one of the places above. A project that uses a pack of its own carries it
along: send the project or its `.civil` archive and the pack goes with it.

## How to override a code value

You don't need a pack of your own to change one value for one project. Any value of the pack in
force can be overridden in the project:

1. Open **02 Project Settings → Code Values**.
2. Pick the table (`factors`, `seismic`, `combinations`, ...) and find the value. The filter
   matches words of its name.
3. Type the project's value in **This project**. Leave the field empty and the pack's value
   applies.

Overridden values are marked and listed first, each with a **Reset** button. The setting behind
the page is `codeOverrides` in `project-settings.json`, a map from a value's path to the
project's value:

```json
"codeOverrides": {
  "factors.phi.shear": 0.7,
  "seismic.systems.rcSmf.R": 7,
  "combinations.pDeltaPreload": { "D": 1.4, "SD": 1.4, "F": 1.4, "L": 0.5 },
  "combinations.strength[1.2D + 1.6L + 0.5Lr].factors.L": 1.7
}
```

- A path is the table, then the keys inside it, separated by dots. A key with dots or brackets
  in it goes in brackets. An item of a list is named by its `name` (or `id`, or its index).
- A value replaces the pack's value. A group of values (`{...}`) replaces the whole group.
- Every run uses the overrides: the analysis, the design, the drawings and the report read the
  pack with the overrides merged in, by the same merge as `extends`.
- Each override is checked against its table. An override of a value the pack does not have, of
  another kind (text for a number), or out of range (a φ above 1) is not used. It is listed with
  its path among the settings' problems and the report's warnings, and the pack's value applies.
- The overrides belong to the project, not to the pack. After switching packs they apply to the
  new pack; one the new pack has no value for is reported, not used.
- The design report lists them in **Code values overridden in this project**: the path, the
  pack's value and the project's value.

Values that belong to a member or a material (a material's E, a member's cover) are still set
on the member or material.

A few owner decisions also have their own setting, because the choice is a common one:
`analysis.partitionAllowanceCase`, `analysis.massSource.partitions` (how the partition counts in the seismic weight), `analysis.steelRigidZoneFactor` and
`site.flood.waveCombination` (see [engineering-decisions.md](engineering-decisions.md)). They
win over the pack's value and over an override of it.

### Switching packs and missing packs

Changing the pack, a setting or an override takes effect on the next run. Nothing needs to be
migrated. The kept results of a run (the design checks, the response spectrum design, the
irregularity checks) are stamped with a fingerprint of the pack's values and the overrides, so a
change never leaves an older answer in use.

A project whose pack is not installed on this computer (a project sent without its pack, say)
still opens and runs. The default pack is used instead, with a warning in Project Settings, on
the Code Values page and in the report.

### Generic defaults

A pack that lacks one value still works. The value comes from SAEngine's **generic defaults**,
`python/src/saengine/codes/generic/data/<table>.json`. These are editable data, not part of any
code. Results and the report name each one as "generic default (SAEngine practice), not given by
<pack>", and the report lists them under **Generic defaults** with their sources:

| Value | Generic default | Source |
| --- | --- | --- |
| `factors.phi.plain` | 0.60 | ACI 318-19 Table 21.2.1(g) |
| `detailing.bars` | hooks, bends, development, laps, splice zones, extents | ACI 318-19 Ch. 25, 18.6-18.10, 9.7.3, 8.7.4; ACI 318-14 25.4.3.2 (hook factors); no lap splices above 36 mm (25.5.1.1) |
| `combinations.pDeltaPreload` | 1.2 D, SD, F; 1.0 L | ASCE 7-22 Sec 2.3.6, combination 6 |
| `seismic.stabilityGravity` | 1.0 each | ASCE 7-22 Sec 12.8.7 |
| `areaLoads.partitions.loadCase` | L | ASCE 7-22 Sec 4.3.2 |
| `seismic.partitionWeight` | full | ASCE 7-22 Sec 12.7.2 (partitions in the seismic weight) |
| `flood.waveCombination` | sum | SAEngine practice (conservative) |
| `steelSeismic.practice.rigidZoneMax` | 0 | SAEngine practice (centreline model) |
| `concrete.modulus` | 4700 √f'c; 0.043 wc^1.5 √f'c | ACI 318-19 19.2.2.1 (brick aggregate: no generic rule, the normal-weight value) |
| `concrete.shrinkage` | 0.0020 below fy 420; 0.0018 × 420/fy, at least 0.0014 | ACI 318-14 Table 24.4.3.2 |

Generic defaults fill single values only, in tables the pack has. A whole table the pack lacks
is a feature it does not cover: that feature shows as "not covered by the code pack", and never
falls back to another code. A value the pack gives always wins, and a project override wins over
both.

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
  `tensionRupture`, `compression`, `flexure`, `shear`; `steel.slenderness`) and the steel shear
  modulus (`materials.steelShearModulus`);
- the code the report and the design method name (the manifest's `basis`);
- the cracked-section stiffness factors of the analysis model, the slender column design and
  the building generator's drift estimate (`concrete.crackedStiffness`, with `wallUncracked`
  for walls taken as uncracked);
- the concrete design's bar sizes, spacings and steel ratios (`concrete.barDiameters`,
  `spacingStep`, `minSlabSpacing`, `minStirrupSpacing`, `columnRho`, `beamRatioMax`), the slab
  design's punching φ, least strain and two-way thicknesses (`factors.phi.punching`,
  `concrete.slabStrainMin`, `concrete.twoWayThickness`), the stairs (`concrete.cover.stair`,
  `combinations.gravity`) and the building generator's slab and beam depths
  (`concrete.twoWayThickness`, `oneWaySlabThickness`, `beamThickness`);
- the walls (`concrete.walls`, `detailing.walls`, `factors.phi`: `shearSeismic`,
  `diagonalCoupling`, the wall, boundary and hoop bar sizes), the seismic detailing of special
  moment frames and their joints (`detailing.special`, `detailing.joints`, `factors.phi.joint`)
  and the lintels (`detailing.lintels`, `concrete.cover.lintel`, the lintel bar sizes);
- 9 Substructure's design report and its sizing assistant: the piles (`foundations`:
  `pileSafety`, `pileControls`, `partialSkin`, `partialBase`, `sptSafety`, `noLoadTestSafety`,
  `loadTestSafety`) and the pile caps (`foundations.strutAndTie`, `factors.phi.strutAndTie`,
  `concrete.cover.pileCap`);
- the steel member design's section table (`steelSections`: the shapes the design checks,
  their dimensions and the steel density).

**What does not follow it yet** (read from the built-in BNBC 2020 values, whatever the pack):
the concrete section design's φ factors and constants (`factors.phi`: `tension`,
`compressionTied`, `compressionSpiral`, `shear`; `materials`: `concreteStrain`, `steelE`;
`concrete`: `fytShearMax`, `slendernessLimit`), the slender column limits
(`concrete.slender`, `factors.phi.stiffnessReduction`), the steel connection factors
(`steel.phi`: `bolt`, `bearing`, `blockShear`, `weld`, `plateFlexure`; `steel.netAreaMax`), the
seismic analysis checks of `fem/seismic_design` (`seismic`: `minimumScale`,
`accidentalEccentricity`, `orthogonalShare`, `massParticipation`, the torsion limits); the
pile and pile cap checks Part 9's editor runs while you type, and the bill of quantities' lintel
bearing and cover (they read the tables above, but of BNBC 2020 until they run under the
project's pack); the analysis exporters' and importers' cracked factors; the soil part
(liquefaction's site factors); the settings editor's derived-value hints and its Code Values
panel; the building services (`plumbing`, `hvac`, `electrical`, `fire`: 07 MEP runs under the
default pack, BNBC 2020 or a user copy that replaces it) and the steel section table wherever it
is read outside the member design (the 04 Objects section list, the bill of quantities, the
drawings, the importers and exporters). A pack's values in those tables are validated and
shown, but not used: keep them equal to BNBC 2020 until a later version wires them. No design
function consults hooks yet. A pack written before a table moved into the code pack (code packs
3: the services tables and `steelSections`) that has no copy of it reads BNBC 2020's.

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

## Planned code packs

SAEngine is built on BNBC 2020. Three more design-code packs are planned. They are listed under
*Planned Design Codes* on the Packages page and shown disabled ("Planned") in the New Building
wizard's design code selector. Each has a page that describes its coverage:

- **ACI 318-19 + ASCE 7-22** (United States).
- **Eurocodes EN 1990–1998 with National Annexes**. There is one base pack with the
  recommended values. Each country's National Annex is a small pack that `extends` the base
  and sets only its Nationally Determined Parameters, in the same way an office pack extends
  BNBC 2020 today. **The loads part is built in** (see below); the materials are planned.
- **Indian Standards**: IS 456, 1893, 800, 875 and 13920. **The loads part is built in** as
  `is-codes` (see below); the materials (IS 456, 800, 13920) are planned.

### Eurocodes (loads and seismic): `eurocodes`

The built-in pack `eurocodes` (Eurocodes, recommended values) covers EN 1990, EN 1991-1-1,
-1-3, -1-4, -1-7 Annex D and EN 1998-1. Its README
(`python/src/saengine/codes/packs/eurocodes/README.md`) lists the tables, and `VERIFY.md` lists
every value with its clause, for checking against the printed codes. It extends BNBC 2020.
Concrete members, slabs, stairs, walls, joints, spread footings and piles design by its EN
1992-1-1, EN 1998-1 and EN 1997-1 methods (below); steel, timber, masonry, deep beams and the
other areas still use the BNBC 2020 tables and methods. The report's design method says which.

To use it, choose **Eurocodes (recommended values)** as the design code. The pack has no towns
(the National Annex maps give agR and vb,0), so set Location to **Custom** and enter agR (in g)
as Z and vb,0 as V. Then choose the terrain category (0, I, II, III or IV) under Wind and the
ground snow load sk under Site → Snow.

It chooses generic methods by id, which other packs can use too:

| Key | Values | What it does |
| --- | --- | --- |
| `seismic.designSpectrum.method` | `reducedElastic` (default), `behaviourFactor` | The design spectrum with q and the lower bound β |
| `seismic.spectrumType`, `seismic.spectra` | spectrum id → site parameters | Type 1 or Type 2 |
| `seismic.lateralForce` | `correction`, `periodTcFactor`, `minStoreys`, `distribution` (`heightPower`, `linear`) | λ, and how the base shear is distributed |
| `seismic.driftAmplification` | `overImportance` (default), `displacementFactor` | Cd·δe/I, or qd·de |
| `seismic.stability.method` | `elasticOverImportance` (default), `designDrift` | θ |
| `wind.method` | `powerLaw` (default), `peakVelocityPressure` | Storey forces from qz, or from qp(z) with cpe, ρ and cscd |
| `liveReduction.method` | `influenceArea` (default), `areaAndStoreys` | KLL·AT, or αA and αn |
| `combinations.strengthSet`, `strengthSets` | set id → combinations | EN 1990 6.10 or 6.10a/b |

#### Concrete and foundation methods (method selection)

The concrete and foundation design asks `saengine.design.method_selection` which method the
pack in force picks for each area, by id, from the pack's method tables `concreteMethods` and
`geotechnicalMethods` (`<area>.method`, or the group's presence). No id (a pack without the
group, such as BNBC 2020) is the default: the strength design with φ, unchanged. Any pack can
pick these ids; another code's method gets its own id and module beside them.

| Area | Ids | Where it is used |
| --- | --- | --- |
| `ultimate` | `partialFactors` | Sections with fcd, fyd, φ = 1 (`rc`, slabs and stairs strips, walls' and flanges' integration, lintels, footing strips); Design Reinforcement's sizing (`bars`) |
| `shear` | `variableStrut` | Beams, columns, walls' in-plane shear, slab and footing strips (VRd,c), the proposal's links |
| `torsion` | `thinWalledVariableStrut` | Beam torsion rows and the torsion the proposal adds |
| `deflection` | `spanDepthK` | Beam span/depth rows (the calculated deflection follows where a span exceeds it) |
| `cracking`, `serviceStress` | `directWidth`, `stressLimits` | Beam crack widths and stress limits (they replace the bar-spacing crack control) |
| `slenderness` | `nominalCurvature` | Column slenderness: λlim and the nominal curvature MEd |
| `punching` | `controlPerimeter` | Flat slabs (shells and frame methods) |
| `memberSteel` | (the group) | Least and largest steel and spacings of beams, columns, slabs, stairs and walls, in the checks and the proposal |
| `anchorage` | `bondStress` | Anchorage and lap lengths of the detailing and the bar schedule |
| `seismic` | `curvatureDuctility` | DCM/DCH members, joints, capacity-design shear, ductile walls; the parent's special-frame detailing does not run |
| `bearing`, `sliding` | `effectiveArea`, `interfaceFriction` | Spread footings by the design approach (the allowable-pressure rows are then reported only) |
| `piles` | `correlationFactors` | Pile caps' piles: Rc,k with ξ, Rc,d by the resistance sets |

A project can set any area back to the default method with the override
`concreteMethods.parentMethods` (or `geotechnicalMethods.parentMethods`), a list of area
names, e.g. `"concreteMethods.parentMethods": ["torsion", "seismic"]`. The design approach is
the override `geotechnicalMethods.designApproach` (DA1, DA2, DA3).

### Indian Standards (loads and seismic): `is-codes`

The built-in pack `is-codes` (Indian Standards (IS)) covers IS 875 Parts 1 and 2 (unit weights,
imposed loads and their reduction by the floors carried), Part 3:2015 (wind: Vz = Vb k1 k2 k3
k4, pz = 0.6 Vz², pd = Kd Ka Kc pz ≥ 0.7 pz), Part 5 with IS 456 Table 18 (combinations) and IS
1893 (Part 1):2016 (zones II-V, soil types I-III, Ah = (Z/2)(I/R)(Sa/g), Ta, the least base
shear, Qi by hi², scaling to VB, drift 0.004, irregularities). It extends BNBC 2020 for the
materials, as `eurocodes` does. Its README and `VERIFY.md` (every value, its clause and how sure
it is) are in `python/src/saengine/codes/packs/is-codes/`.

It has towns: choosing it in **New Project** or the **New Building** wizard lists its 67 cities
(zone and basic wind speed), soil types and terrain categories, and a new project starts from
the pack's defaults (Delhi, soil type II, RC SMRF, terrain category 2, its live loads and
combinations), every one changeable in Project Settings. k3 is the topographic factor of Project
Settings → Wind, k4 the Code Values override `wind.speedFactors.importance`.

The generic methods and keys it adds, open to any pack:

| Key | Values | What it does |
| --- | --- | --- |
| `seismic.designSpectrum` (`reducedElastic`) | `factor`, `longPeriod` (`inverseSquare`, `constant`), `staticPlateau` | Sa = factor·Z·I/R·Cs; Sa/g constant beyond TD; no rising branch in the static method |
| `seismic.lateralForce` | `distribution: heightSquared`, `minimumShare` by zone | Qi ∝ Wi hi²; the least V / W |
| `seismic.driftAmplification` | `designForces` | Drift checked as computed; displacements Cd·de (Cd = R) |
| `seismic.periodCoefficients.<family>.planDimension` | true | T = Ct·h^m/√d |
| `wind.method` | `speedFactors` (with `speedFactors`, `cpByHeight`) | pd from the design wind speed; wall Cp by h/w and l/w |
| `liveReduction.method` | `floorCount` | Reduction by the floors carried, beams by area |
| `locations.default`, `seismic.defaultSiteClass`, `seismic.defaultSystem`, `wind.defaultExposure` | ids | A new project's choices under the pack |
| `snow` (table) | | s = factor·μ1·Ce·Ct·sk on the roof, in Lr |

A National Annex pack extends it and gives only what differs:

```json
{ "schema": "saengine.codePack/1", "id": "ec-xx", "name": "Eurocodes with the XX National Annex",
  "extends": "eurocodes", "covers": ["combinations", "seismic"] }
```

For example, `data/combinations.json` can be `{"strengthSet": "6.10ab"}` and
`data/seismic.json` `{"spectrumType": "2", "designSpectrum": {"lowerBound": 0.1}}`.

The US and Indian packs have none of their tables, values or clause text included yet.

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

A full building template (`template.civil`) must hold inputs only: an archive with results, a
soil report (`01 Soil Report`), deliverables (`11 Exports`) or the version history (`.git`) is
refused by `validate` and by the install.

SAEngine ships one template package built in: `saengine-shapes`, the presets of the six
parametric shapes (their Generate panel starting values, which the tests keep equal to the
panel's, and a few named variants). It and BNBC 2020 are also published, as read-only mirrors, in
the marketplace's package repositories: edit them here and copy them there with
`scripts/marketplace/mirror_packages.py` (the repositories' CI refuses a mirror that differs from
the SAEngine commit it names).

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
